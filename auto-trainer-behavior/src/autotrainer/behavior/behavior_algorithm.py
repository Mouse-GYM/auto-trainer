import contextlib
import copy
import dataclasses
import enum
import functools
import inspect
import logging
import math
import operator
import os
import queue
import statistics
import threading
import time
from collections import deque
from datetime import datetime
from functools import partial
from functools import reduce
from pathlib import Path
from typing import Callable, Optional, Tuple, List, ClassVar, Any, Union, Dict

from typing import Callable

from typing_extensions import Self

from autotrainer.core.logging import get_verbose_logger
from autotrainer.core import ObservableObject, EventManager, post_trigger_enable, Offset3DTuple, \
    AnimalSubject
from autotrainer.core.configuration.behavior_configuration import PelletDeliveryConfiguration, HeadClampConfiguration, \
    BehaviorConfiguration, AutoCloseGateOnIntersessionConfiguration
from autotrainer.core import ApiEventKind as BehaviorEventKind
from autotrainer.core.video_detection import PresenceDetectionAttrs

from autotrainer.video import CaptureProcessStatus

from . import DiamondTriangleOffsetConfig, CaptureAnalysisResult, TrainingMode
from .system_machine_state import SystemState
from .intersession import IntersessionState

logger = get_verbose_logger(__name__)


class CheckThresholdWay(str, enum.Enum):
    TRIGGER_IF_GREATER = "trigger_if_greater"
    TRIGGER_IF_SMALLER = "trigger_if_smaller"


class CoverServoStatus(int, enum.Enum):
    OK = 0
    COVER_POSITION_ERROR = 1
    RELEASE_POSITION_ERROR = 2

    COVER_AND_RELEASE_POS_ERROR = COVER_POSITION_ERROR | RELEASE_POSITION_ERROR

    @property
    def is_error(self):
        return self is not CoverServoStatus.OK


@dataclasses.dataclass
class CheckElementDistanceContext:
    distance_property_name: str
    cover_servo_status: CoverServoStatus
    error_way: CheckThresholdWay
    error_distance_threshold: float
    error_min_duration_threshold: float = math.inf  # unit is second

    distance: float = 0  # unit probably millimeter
    error_detected: bool = False
    error_start_timestamp: Optional[float] = None


class BehaviorAlgoProps(str, enum.Enum):

    ALGO_PAUSED = 'algo_paused'

    AUTO_CLAMP_INTENSITY = 'auto_clamp_intensity'
    BASELINE_INTENSITY = 'baseline_intensity'
    DAY_PELLET_COUNT = 'day_pellet_count'  # consumed
    TOTAL_PELLET_COUNT = 'total_pellet_count'  # consumed
    DAY_PELLET_PRESENTED = 'day_pellet_presented'
    TOTAL_PELLET_PRESENTED = 'total_pellet_presented'
    DAY_SUCCESSFUL_REACHES = 'day_successful_reaches'
    TOTAL_SUCCESSFUL_REACHES = 'total_successful_reaches'
    HEAD_FIXATION_ENABLED = 'head_fixation_enabled'
    INTERSESSION_ENABLED = 'intersession_enabled'
    INTERSESSION_PELLET_SHIFT_ENABLED = 'intersession_pellet_shift_enabled'
    PELLET_DELIVERY_ENABLED = 'pellet_delivery_enabled'
    PELLET_COVER_ENABLED = 'pellet_cover_enabled'
    SESSION_PELLET_COUNT = 'session_pellet_count'
    SESSION_MOUSE_SEEN = 'session_mouse_seen'

    AUTO_CORRECT_MOTOR_DRIFT = 'auto_correct_motor_drift'
    PELLET_MOTOR_DRIFT = 'pellet_motor_drift'
    COVER_SERVO_STATUS = 'cover_servo_status'
    COVER_PELLET_DISTANCE = "cover_pellet_distance"
    RELEASE_PELLET_DISTANCE = "release_pellet_distance"

    IS_IN_SESSION = 'is_in_session'
    INTERSESSION_STATE = 'intersession_state'
    CAPTURE_STATUS = 'capture_status'

    USE_TRIANGLE_PELLET_DISTANCE_TOO_FAR = "use_triangle_pellet_distance_too_far"
    TRIANGLE_PELLET_DISTANCE = "triangle_pellet_distance"

    PRESENCE_MISSING = 'presence_missing'
    PELLET_HANDS_DISTANCE = 'pellet_hands_min_distance'
    HANDS_NEAR_PELLET_SEEN = 'hands_near_pellet_seen'

#

# this define the default behavior for handling  relay of function call to the dedicated algo thread handler,
# True: "wait" that the function is executed on the algo handler thread before proceeding,
# False: do not wait that the function is executed, submit it, and then continue immediately.
#
_DEFAULT_ALGO_HANDLER_THREAD_CALL_SYNC_WAIT_MODE = True
# True: safer for all
# False: faster for caller/putter


def _relay_func(func, *, wait: bool=_DEFAULT_ALGO_HANDLER_THREAD_CALL_SYNC_WAIT_MODE):
    """See BehaviorAlgorithm.relay_func()"""
    orig_func = func
    # skip any partial(s):
    while isinstance(func, partial):
        func = func.func

    # handle bound method vs normal function:
    @functools.wraps(func.__func__ if inspect.ismethod(func) else func)
    def wrapped(*args, **kwargs):
        BehaviorAlgorithm.put_func_call(orig_func, args, kwargs, wait=wait)

    return wrapped

#
# shift xyz handling:

ShiftXYZCallbackHandlerT = Callable[[Offset3DTuple], Optional[Offset3DTuple]]
# takes an xyz, and returns None for no further action.
# or return a "result/processed" xyz, that can be passed along.

BufferShiftXYZCallbackHandlerT = Callable[[List[Offset3DTuple]], Offset3DTuple]


class ShiftXYZBufferHandler:

    @staticmethod
    def make_average(buffer: List[Offset3DTuple]):
        return sum(buffer) / len(buffer)

    def __init__(self, size: int):
        self._buffer = []
        self._size = size
        self._reduce_func = self.make_average

    @property
    def size(self):
        return self._size

    @size.setter
    def size(self, value):
        self._size = value

    def __call__(self, xyz: Offset3DTuple):
        buff = self._buffer
        buff.append(xyz)
        if len(buff) < self._size:
            return None
        res = self._reduce_func(buff)
        buff.clear()
        return res

    def set_reduce_buffer_func(self, func: BufferShiftXYZCallbackHandlerT):
        self._reduce_func = func


class ShiftXYZHandler(ObservableObject):

    def __init__(self):
        super().__init__()
        default_handler = ShiftXYZBufferHandler(int(os.getenv("HANDLE_SHIFT_XYZ_BUFFER_SIZE", 10)))
        self._handle_new_shift_xyz_func: ShiftXYZCallbackHandlerT = default_handler
        self._handle_processed_shift_func: Optional[ShiftXYZCallbackHandlerT] = None
        self._last_shift_xyz: Optional[Offset3DTuple] = None
        self._last_processed_shift_xyz: Optional[Offset3DTuple] = None

    LAST_SHIFT_XYZ = "last_shift_xyz"

    @property
    def last_shift_xyz(self) -> Offset3DTuple:
        return self._last_shift_xyz

    @last_shift_xyz.setter
    def last_shift_xyz(self, value):
        prev, self._last_shift_xyz = self._last_shift_xyz, value
        # use property_changed, which always call the property changed callbacks, even if same value than prev:
        self.property_changed(self.LAST_SHIFT_XYZ, value, prev)

    #

    LAST_PROCESSED_SHIFT_XYZ = "last_processed_shift_xyz"

    @property
    def last_processed_shift_xyz(self) -> Offset3DTuple:
        return self._last_processed_shift_xyz

    @last_processed_shift_xyz.setter
    def last_processed_shift_xyz(self, value):
        prev, self._last_processed_shift_xyz = self.last_processed_shift_xyz, value
        # use property_changed, which always call the property changed callbacks, even if same value than prev:
        self.property_changed(self.LAST_PROCESSED_SHIFT_XYZ, value, prev)

    #

    @property
    def handle_new_shift_xyz_func(self) -> Optional[Union[ShiftXYZCallbackHandlerT]]:
        return self._handle_new_shift_xyz_func

    def set_handle_new_shift_xyz(self, func: ShiftXYZCallbackHandlerT):
        self._handle_new_shift_xyz_func = func

    def set_handle_processed_shift_xyz(self, func: Optional[ShiftXYZCallbackHandlerT]):
        self._handle_processed_shift_func = func

    def put_new_shift_xyz(self, shift_xyz: Offset3DTuple):
        self.last_shift_xyz = shift_xyz
        res = self._handle_new_shift_xyz_func(shift_xyz)
        if res is not None:
            self.last_processed_shift_xyz = res
            func = self._handle_processed_shift_func
            if func is None:
                logger.debug("handle_processed_shift_func undefined")
            else:
                func(res)  # noqa
                # not sure why need noqa otherwise PyCharm think it's None .. despite the previous if .. :/

#

class BehaviorAlgorithm(ObservableObject):
    # dynamic events type hints,
    # helps IDE search/completion/type-verification:
    session_starting: Callable[[], None]
    session_ending: Callable[[], None]
    session_processing_ending: Callable[[CaptureAnalysisResult], None]

    pellet_motor_drift_changed: Callable[[Offset3DTuple], None]
    cover_servo_status_changed: Callable[[CoverServoStatus], None]

    pellets_presented_evt: Callable[[int], None]
    pellets_consumed_evt: Callable[[int], None]
    successful_reaches_evt: Callable[[int], None]

    #

    _thread_locals: ClassVar[threading.local] = threading.local()
    _handler_thread_queue: ClassVar[Tuple[threading.Thread, Optional[queue.Queue]]] = (threading.current_thread(), None)
    _no_handler_thread: ClassVar[Optional[bool]] = False

    def __init__(
        self,
        *,
        cover_error_min_distance_threshold: float = 2,  # millimeter
        release_error_min_distance_threshold: float = 2,  # millimeter
        cover_release_min_duration_threshold: float = 3,  # seconds
        diamond_triangle_offset_config_path: Optional[Path] = None,
        topcam_presence: Optional[PresenceDetectionAttrs] = None,
    ):
        super().__init__(event_names=(
            "session_starting",
            "session_ending",
            "session_processing_ending",
            "cover_servo_status_changed",
            "pellet_motor_drift_changed",
            "pellets_presented_evt",  # Some unfortunate names for now given existing property names
            "pellets_consumed_evt",
            "successful_reaches_evt"
        ))
        self._thread_lock = threading.RLock()
        self._project_info = None

        self._pellet_delivery_enabled = True
        self._pellet_cover_enabled = True

        self._intersession_enabled = False
        self._intersession_pellet_shift_enabled = False
        self._head_fixation_enabled = False
        self._clean_raw_data_on_inactive_session = False
        self._auto_correct_motors_drift = False
        self._auto_clamp_intensity = 100
        self._auto_clamp_release_tone_freq = 7000
        self._auto_clamp_release_tone_delay = 0.1
        self._auto_clamp_release_load_count = HeadClampConfiguration.auto_clamp_release_load_count
        self._auto_clamp_no_activity_release_delay = HeadClampConfiguration.auto_clamp_no_activity_release_delay

        self._recording_age_release_pellet_threshold = 0.75
        self._recording_prebuffer_duration = 0

        self._algo_paused = False
        self._algo_paused_perf_t = 0
        self._is_in_session = False
        self._start_session_reason = "NA"
        self._stop_session_reason = "NA"

        self._session_mouse_seen = False
        self._pellet_seen = False
        self._pellet_last_seen = 0.0
        self._pellet_hands_min_distance: float = math.inf
        self._hands_near_pellet_seen = False
        self._triangle_seen = False
        self._triangle_last_seen = 0.0
        self._triangle_pellet_last_offset = Offset3DTuple(math.nan, math.nan, math.nan)
        self._use_triangle_pellet_distance_too_far = False
        self._triangle_pellet_diff_too_far_threshold: float = (
            PelletDeliveryConfiguration.triangle_pellet_diff_too_far_threshold)
        self._triangle_pellet_expected_distance = PelletDeliveryConfiguration.triangle_pellet_expected_distance
        self._diamond_last_seen = -math.inf
        self._next_diamond_triangle_log_report = time.perf_counter()
        self._star_last_seen = -math.inf

        self._system_state = SystemState.cage
        self._intersession_state = IntersessionState.idle
        self._capture_status = CaptureProcessStatus.UNKNOWN
        self._last_capture_status_change_perf_c = -math.inf

        self._loaded_config: Optional[BehaviorConfiguration] = None

        self.min_baseline_intensity: float = 5.0
        self.max_baseline_intensity: float = 90.0
        self._baseline_intensity = self.min_baseline_intensity
        self.baseline_intensity_increment: float = 15.0
        self.max_pellets_per_session: int = 10
        self.max_pellets_per_headfix_session: int = 10
        self.max_pellets_per_day: int = 50
        self.pellet_missing_time: float = 1.0
        self.triangle_missing_time: float = 1.0
        self.pellet_hand_uncover_distance = PelletDeliveryConfiguration.pellet_hand_uncover_distance

        self.auto_close_gate_on_intersession_config = AutoCloseGateOnIntersessionConfiguration()

        self._pellet_count_day = 0  # consumed
        self._pellet_count_session = 0  # consumed
        self._pellet_count_total = 0  # consumed
        self._pellets_presented_day: int = 0
        self._pellets_presented_total: int = 0
        self._successful_reaches_day: int = 0
        self._successful_reaches_total: int = 0

        self._cover_servo_status = CoverServoStatus.OK

        self._topcam_presence: Optional[PresenceDetectionAttrs] = topcam_presence
        self._presence_missing = False

        if diamond_triangle_offset_config_path is None:
            diamond_triangle_offset_config_path = DiamondTriangleOffsetConfig.DEFAULT_CONFIG_PATH
        self._diamond_triangle_offset_config_path = diamond_triangle_offset_config_path
        self._diamond_triangle_offset_config = DiamondTriangleOffsetConfig.load_config(
            self._diamond_triangle_offset_config_path
        )

        self._diamond_triangle_drift: Optional[Offset3DTuple] = None
        self._diamond_triangle_prev_drifts: List[Offset3DTuple] = []
        self._diamond_triangle_last_drift_report = time.perf_counter()

        self._cover_pellet_distance_ctx = CheckElementDistanceContext(
            distance_property_name=BehaviorAlgoProps.COVER_PELLET_DISTANCE,
            error_distance_threshold=cover_error_min_distance_threshold,
            error_min_duration_threshold=cover_release_min_duration_threshold,
            error_way=CheckThresholdWay.TRIGGER_IF_SMALLER,
            cover_servo_status=CoverServoStatus.COVER_POSITION_ERROR,
        )
        self._release_pellet_distance_ctx = CheckElementDistanceContext(
            distance_property_name=BehaviorAlgoProps.RELEASE_PELLET_DISTANCE,
            error_distance_threshold=release_error_min_distance_threshold,
            error_min_duration_threshold=cover_release_min_duration_threshold,
            error_way=CheckThresholdWay.TRIGGER_IF_GREATER,
            cover_servo_status=CoverServoStatus.RELEASE_POSITION_ERROR,
        )
        #
        self._check_start_thread()
        self._today = None
        self._start_day()
        #
        self._shift_xyz_handler = ShiftXYZHandler()

    @classmethod
    def _check_start_thread(cls):
        if cls._no_handler_thread:
            return
        _, handler_queue = cls._handler_thread_queue
        if handler_queue is None:
            logger.info("Creating algo handler thread ..")
            handler_queue = queue.Queue(maxsize=64)
            handler_thread = threading.Thread(
                target=cls._handler_thread_run, args=(handler_queue,),
                daemon=True,
                name="AlgoHandler",
            )
            cls._handler_thread_queue = (handler_thread, handler_queue)
            handler_thread.start()

    @staticmethod
    @contextlib.contextmanager
    def set_put_func_call_mode(wait: bool):
        """Allow to set the "sync" call mode for other threads putting func calls to our dedicated algo thread
        with algo.set_put_func_call_mode(False):
            # some code going via algo.put_func_call will use the given mode (async here)
            # but then:
            with algo.set_put_func_call_mode(True):
                # some code going via algo.put_func_call will use the given mode (sync here)
            # and here:
            # some code going via algo.put_func_call will use the given mode (async here)
        # some code going via algo.put_func_call will use the default mode (sync here)
        """
        t_locals = BehaviorAlgorithm._thread_locals
        prev = getattr(t_locals, "sync_call_mode", None)
        t_locals.sync_call_mode = wait
        yield
        t_locals.sync_call_mode = prev

    @staticmethod
    def relay_func(func=None, *, wait: bool=_DEFAULT_ALGO_HANDLER_THREAD_CALL_SYNC_WAIT_MODE):
        """Decorator for marking a function/method as having to be relayed to our algo dedicated thread"""
        if func is None:
            return partial(_relay_func, wait=wait)
        return _relay_func(func, wait=wait)

    @staticmethod
    def _handler_thread_run(input_queue: queue.Queue):
        logger.verbose("Running for handling/executing all algo decision/transition ..")
        while True:
            raw = input_queue.get()
            if raw is None:
                input_queue.task_done()
                break
            func, args, kwargs, event = raw
            try:
                func(*args) if kwargs is None else func(*args, **kwargs)
            except Exception as err:
                logger.exception("Failed executing %s: %s", func, err)
                # NB: what to do else ?
                # this is a pretty critical situation given the related function might be itself critical.
                # TODO: maybe relay a flag/msg/error to the main thread for display purpose ?
                # actually this should even trigger a restart of the application.
            if event is not None:
                event.set()
            input_queue.task_done()
        logger.debug("Exiting ; left queue_size=%s", input_queue.qsize())

    @classmethod
    def relay_transitions(cls, machine_transitions: Any):
        """Relay all transition triggers of the given machine_transitions instance to the algo dedicated thread"""
        for trans in machine_transitions.transitions:
            trig = trans['trigger']
            if trig is not None:
                if callable(trig):
                    trig = trig.__name__
                meth = getattr(machine_transitions, trig)
                setattr(machine_transitions, trig, cls.relay_func(meth))

    @classmethod
    def put_func_call(cls, func, args: Tuple[Any], kwargs: Optional[Dict]=None,
                      *, wait: bool=_DEFAULT_ALGO_HANDLER_THREAD_CALL_SYNC_WAIT_MODE):
        """Put a function call request to the algo dedicated thread, and eventually wait on its completion.
        See also `BehaviorAlgorithm.set_put_func_call_mode`.
        """
        handler_thread, handler_queue = BehaviorAlgorithm._handler_thread_queue
        if threading.current_thread() is handler_thread or handler_queue is None or cls._no_handler_thread:
            # logger.debug("%s: in-place execution ; already in system msg handler thread", func)
            func(*args) if kwargs is None else func(*args, **kwargs)
        else:
            t_local_sync = getattr(cls._thread_locals, "sync_call_mode", None)
            if t_local_sync is not None:
                wait = t_local_sync
            # logger.debug("%s: relaying to system msg handler thread", func)
            if wait:
                event = getattr(cls._thread_locals, "event", None)
                if event is None:
                    logger.debug("%s: creating event for sync handling of put_func_call %s",
                                 threading.current_thread(), func)
                    event = cls._thread_locals.event = threading.Event()
            else:
                event = None
            handler_queue.put((func, args, kwargs, event))
            if event is not None:
                event.wait()
                event.clear()  # need always clear after used

    @property
    def thread_lock(self):
        return self._thread_lock

    @property
    def limits(self) -> Self:
        return self

    @property
    def project(self):
        return self._project_info

    @project.setter
    def project(self, project):
        self._project_info = project

    @property
    def algo_paused(self):
        return self._algo_paused

    @algo_paused.setter
    def algo_paused(self, value):
        prev, self._algo_paused = self._algo_paused, value
        if value and not prev:
            self._algo_paused_perf_t = time.perf_counter()
        self._on_property_changed(BehaviorAlgoProps.ALGO_PAUSED, value, prev)

    @property
    def algo_paused_age(self):
        # actually unused.
        return time.perf_counter() - self._algo_paused_perf_t

    @property
    def top_camera_presence_detection(self) -> PresenceDetectionAttrs:
        return self._topcam_presence

    @property
    def system_state(self) -> SystemState:
        return self._system_state

    @system_state.setter
    def system_state(self, value: SystemState):
        self._system_state = value

    @property
    def intersession_state(self) -> IntersessionState:
        return self._intersession_state

    @intersession_state.setter
    def intersession_state(self, value: IntersessionState):
        prev, self._intersession_state = self._intersession_state, value
        self._on_property_changed(BehaviorAlgoProps.INTERSESSION_STATE, value, prev)

    @property
    def capture_status(self) -> CaptureProcessStatus:
        return self._capture_status

    @capture_status.setter
    def capture_status(self, value: CaptureProcessStatus):
        self._last_capture_status_change_perf_c = time.perf_counter()
        self._capture_status = self._on_property_changed(BehaviorAlgoProps.CAPTURE_STATUS, value, self._capture_status)

    @property
    def capture_status_age(self) -> float:
        """Capture status age as number of seconds"""
        return time.perf_counter() - self._last_capture_status_change_perf_c

    @property
    def recording_age_release_pellet_threshold(self) -> float:
        """Desired delay to wait once camera recording-started is detected, to then after release the pellet"""
        return self._recording_age_release_pellet_threshold

    @property
    def is_in_session(self) -> bool:
        return self._is_in_session

    @property
    def pellet_delivery_enabled(self):
        return self._pellet_delivery_enabled

    @pellet_delivery_enabled.setter
    def pellet_delivery_enabled(self, value: bool):
        prev, self._pellet_delivery_enabled = self._pellet_delivery_enabled, value
        self._on_property_changed(BehaviorAlgoProps.PELLET_DELIVERY_ENABLED, value, prev)

    @property
    def pellet_cover_enabled(self):
        return self._pellet_cover_enabled

    @pellet_cover_enabled.setter
    def pellet_cover_enabled(self, value: bool):
        prev, self._pellet_cover_enabled = self._pellet_cover_enabled, value
        self._on_property_changed(BehaviorAlgoProps.PELLET_COVER_ENABLED, value, prev)

    @property
    def intersession_enabled(self):
        return self._intersession_enabled

    @intersession_enabled.setter
    def intersession_enabled(self, value: bool):
        prev, self._intersession_enabled = self._intersession_enabled, value
        self._on_property_changed(BehaviorAlgoProps.INTERSESSION_ENABLED, value, prev)

    @property
    def intersession_pellet_shift_enabled(self):
        return self._intersession_pellet_shift_enabled

    @intersession_pellet_shift_enabled.setter
    def intersession_pellet_shift_enabled(self, value: bool):
        prev, self._intersession_pellet_shift_enabled = self._intersession_pellet_shift_enabled, value
        self._on_property_changed(BehaviorAlgoProps.INTERSESSION_PELLET_SHIFT_ENABLED, value, prev)

    @property
    def head_fixation_enabled(self):
        return self._head_fixation_enabled

    @head_fixation_enabled.setter
    def head_fixation_enabled(self, value: bool):
        prev, self._head_fixation_enabled = self._head_fixation_enabled, value
        if prev != self._head_fixation_enabled:
            logger.info("auto-clamp enabled changed to: %s", self._head_fixation_enabled)
            self._on_property_changed(BehaviorAlgoProps.HEAD_FIXATION_ENABLED, value, prev)

    @property
    def clean_raw_data_on_inactive_session(self):
        return self._clean_raw_data_on_inactive_session

    @clean_raw_data_on_inactive_session.setter
    def clean_raw_data_on_inactive_session(self, value):
        self._clean_raw_data_on_inactive_session = value

    @property
    def baseline_intensity(self):
        return self._baseline_intensity

    @baseline_intensity.setter
    def baseline_intensity(self, value):
        prev, self._baseline_intensity = self._baseline_intensity, value
        if value != prev:
            EventManager.default().post_event_content(BehaviorEventKind.headfixBaselineChanged, context=value)
            self._on_property_changed(BehaviorAlgoProps.BASELINE_INTENSITY, value, prev)

    @property
    def auto_clamp_intensity(self):
        return self._auto_clamp_intensity

    @auto_clamp_intensity.setter
    def auto_clamp_intensity(self, value):
        prev, self._auto_clamp_intensity = self._auto_clamp_intensity, value
        if value != prev:
            self._on_property_changed(BehaviorAlgoProps.AUTO_CLAMP_INTENSITY, value, prev)
            EventManager.default().post_event_content(BehaviorEventKind.autoClampIntensityChanged, context=value)

    @property
    def auto_clamp_release_tone_freq(self):
        """Frequency of the tone played when auto-clamp is released in Hz"""
        return self._auto_clamp_release_tone_freq

    @auto_clamp_release_tone_freq.setter
    def auto_clamp_release_tone_freq(self, value):
        prev, self._auto_clamp_release_tone_freq = self._auto_clamp_release_tone_freq, value
        if value != prev:
            self._on_property_changed("auto_clamp_release_tone_freq", value, prev)
            EventManager.default().post_event_content(BehaviorEventKind.autoClampReleaseToneFreqChanged, context=value)

    @property
    def auto_clamp_release_tone_delay(self):
        return self._auto_clamp_release_tone_delay

    @auto_clamp_release_tone_delay.setter
    def auto_clamp_release_tone_delay(self, value):
        prev, self._auto_clamp_release_tone_delay = self._auto_clamp_release_tone_delay, value
        if value != prev:
            self._on_property_changed("auto_clamp_release_tone_delay", value, prev)
            EventManager.default().post_event_content(BehaviorEventKind.autoClampReleaseDelayChanged, context=value)

    @property
    def auto_clamp_release_load_count(self):
        return self._auto_clamp_release_load_count

    @auto_clamp_release_load_count.setter
    def auto_clamp_release_load_count(self, value):
        self._auto_clamp_release_load_count = value

    @property
    def auto_clamp_no_activity_release_delay(self):
        return self._auto_clamp_no_activity_release_delay

    @auto_clamp_no_activity_release_delay.setter
    def auto_clamp_no_activity_release_delay(self, value):
        self._auto_clamp_no_activity_release_delay = value

    #

    @property
    def record_prebuffer_duration(self) -> float:
        return self._recording_prebuffer_duration

    @record_prebuffer_duration.setter
    def record_prebuffer_duration(self, value):
        self._recording_prebuffer_duration = value

    #

    @property
    def triangle_last_seen(self) -> float:
        return self._triangle_last_seen

    @property
    def star_recently_seen(self) -> bool:
        return time.perf_counter() - self._star_last_seen < self.limits.triangle_missing_time

    @property
    def triangle_recently_seen(self) -> bool:
        return time.perf_counter() - self._triangle_last_seen < self.limits.triangle_missing_time

    @property
    def diamond_recently_seen(self) -> bool:
        return time.perf_counter() - self._diamond_last_seen < self.limits.triangle_missing_time

    @property
    def pellet_last_seen(self) -> float:
        return self._pellet_last_seen

    @property
    def presence_missing(self) -> bool:
        return self._presence_missing

    @presence_missing.setter
    def presence_missing(self, value):
        prev, self._presence_missing = self._presence_missing, value
        self._on_property_changed(BehaviorAlgoProps.PRESENCE_MISSING, value, prev)

    @property
    def triangle_pellet_offset(self) -> Offset3DTuple:
        return self._triangle_pellet_last_offset

    @triangle_pellet_offset.setter
    def triangle_pellet_offset(self, value):
        prev, self._triangle_pellet_last_offset = self._triangle_pellet_last_offset, value
        self._on_property_changed(BehaviorAlgoProps.TRIANGLE_PELLET_DISTANCE, self.triangle_pellet_distance,
                                  prev.distance)

    @property
    def triangle_pellet_distance(self) -> float:
        return self._triangle_pellet_last_offset.distance

    @property
    def use_triangle_pellet_distance_too_far(self) -> bool:
        return self._use_triangle_pellet_distance_too_far

    @use_triangle_pellet_distance_too_far.setter
    def use_triangle_pellet_distance_too_far(self, value):
        prev, self._use_triangle_pellet_distance_too_far = self._use_triangle_pellet_distance_too_far, value
        self._on_property_changed(BehaviorAlgoProps.USE_TRIANGLE_PELLET_DISTANCE_TOO_FAR, value, prev)

    @property
    def triangle_pellet_expected_distance(self):
        return self._triangle_pellet_expected_distance

    @triangle_pellet_expected_distance.setter
    def triangle_pellet_expected_distance(self, value):
        prev, self._triangle_pellet_expected_distance = self._triangle_pellet_expected_distance, value
        # self._on_property_changed(BehaviorProps)

    @property
    def triangle_pellet_diff_too_far_threshold(self):
        return self._triangle_pellet_diff_too_far_threshold

    @triangle_pellet_diff_too_far_threshold.setter
    def triangle_pellet_diff_too_far_threshold(self, value):
        prev, self._triangle_pellet_diff_too_far_threshold = self._triangle_pellet_diff_too_far_threshold, value

    def is_triangle_pellet_distance_too_far(self) -> bool:
        return (
                abs(self.triangle_pellet_distance - self._triangle_pellet_expected_distance)
                >= self._triangle_pellet_diff_too_far_threshold
        ) if self._use_triangle_pellet_distance_too_far else False

    def _set_triangle_last_seen(self, value: float):
        prev, self._triangle_last_seen = self._triangle_last_seen, value
        # self._on_property_changed("triangle_last_seen", value, prev)

    def _set_pellet_last_seen(self, value: float):
        self._pellet_last_seen = self._on_property_changed("pellet_last_seen", value, self._pellet_last_seen)

    @property
    def day_pellet_count(self) -> int:
        return self._pellet_count_day

    @day_pellet_count.setter
    def day_pellet_count(self, value: int):
        prev_value, self._pellet_count_day = self._pellet_count_day, value
        self._on_property_changed(BehaviorAlgoProps.DAY_PELLET_COUNT, value, prev_value)
        incr = value - prev_value
        if incr > 0:
            EventManager.default().post_event_content(BehaviorEventKind.dayIncreasePellet, context=value)
        elif incr < 0:
            EventManager.default().post_event_content(BehaviorEventKind.dayDecreasePellet, context=value)

    @property
    def total_pellet_count(self) -> int:
        return self._pellet_count_total

    @total_pellet_count.setter
    def total_pellet_count(self, value: int):
        prev, self._pellet_count_total = self._pellet_count_total, value
        self._on_property_changed(BehaviorAlgoProps.TOTAL_PELLET_COUNT, value, prev)

    @property
    def session_pellet_count(self) -> int:
        return self._pellet_count_session

    @session_pellet_count.setter
    def session_pellet_count(self, value):
        prev, self._pellet_count_session = self._pellet_count_session, value
        self._on_property_changed(BehaviorAlgoProps.SESSION_PELLET_COUNT, value, prev)
        incr = value - prev
        if incr > 0:
            EventManager.default().post_event_content(BehaviorEventKind.sessionPelletIncrease, context=value)
        elif incr < 0:
            EventManager.default().post_event_content(BehaviorEventKind.sessionPelletDecrease, context=value)
        # if self._pellet_count_session > self.limits.max_pellets_per_session:
        #    self.end_session()

    def increase_pellets_consumed(self, quantity: int = 1):
        self.day_pellet_count += quantity
        self.session_pellet_count += quantity
        self.total_pellet_count += quantity
        if quantity:
            self.pellets_consumed_evt(quantity)

    @property
    def session_mouse_seen(self):
        return self._session_mouse_seen

    @property
    def pellets_presented_day(self):
        return self._pellets_presented_day

    @pellets_presented_day.setter
    def pellets_presented_day(self, value):
        prev, self._pellets_presented_day = self._pellets_presented_day, value
        self._on_property_changed(BehaviorAlgoProps.DAY_PELLET_PRESENTED, value, prev)

    @property
    def pellets_presented_total(self):
        return self._pellets_presented_total

    @pellets_presented_total.setter
    def pellets_presented_total(self, value):
        prev, self._pellets_presented_total = self._pellets_presented_total, value
        if prev != value:
            self._on_property_changed(BehaviorAlgoProps.TOTAL_PELLET_PRESENTED, value, prev)
            EventManager.default().post_event_content(BehaviorEventKind.pelletPresented, context=value)

    def increase_pellets_presented(self, quantity: int = 1):
        self.pellets_presented_day += quantity
        self.pellets_presented_total += quantity
        if quantity:
            self.pellets_presented_evt(quantity)

    #

    @property
    def successful_reaches_day(self):
        return self._successful_reaches_day

    @successful_reaches_day.setter
    def successful_reaches_day(self, value):
        prev, self._successful_reaches_day = self._successful_reaches_day, value
        self._on_property_changed(BehaviorAlgoProps.DAY_SUCCESSFUL_REACHES, value, prev)

    @property
    def successful_reaches_total(self):
        return self._successful_reaches_total

    @successful_reaches_total.setter
    def successful_reaches_total(self, value):
        prev, self._successful_reaches_total = self._successful_reaches_total, value
        if prev != value:
            self._on_property_changed(BehaviorAlgoProps.TOTAL_SUCCESSFUL_REACHES, value, prev)
            EventManager.default().post_event_content(BehaviorEventKind.pelletSuccessfulReach, context=value)

    def increase_successful_reaches(self, quantity: int = 1):
        self.successful_reaches_day += quantity
        self.successful_reaches_total += quantity
        if quantity:
            self.successful_reaches_evt(quantity)

    #

    @property
    def cover_servo_status(self) -> CoverServoStatus:
        return self._cover_servo_status

    @cover_servo_status.setter
    def cover_servo_status(self, status: CoverServoStatus):
        self._cover_servo_status = self._on_property_changed(BehaviorAlgoProps.COVER_SERVO_STATUS,
                                                             status, self._cover_servo_status)
        if status is CoverServoStatus.OK:
            logger.notice("Set cover servo status to %s", status)

    #

    @property
    def diamond_triangle_config(self) -> Optional[DiamondTriangleOffsetConfig]:
        return self._diamond_triangle_offset_config

    @diamond_triangle_config.setter
    def diamond_triangle_config(self, value):
        self._diamond_triangle_offset_config = value

    @property
    def diamond_triangle_drift(self) -> Optional[Offset3DTuple]:
        return self._diamond_triangle_drift

    @property
    def diamond_triangle_offset_config_path(self) -> Path:
        return self._diamond_triangle_offset_config_path

    def animal_pellet_to_motor(self, animal: AnimalSubject) -> Optional[Offset3DTuple]:
        xyz = Offset3DTuple(animal.pellet_x, animal.pellet_y, animal.pellet_z)
        if not animal.is_pellet_dcs:
            return xyz
        cfg = self._diamond_triangle_offset_config
        if cfg is None:
            return None
            # raise RuntimeError(f"Animal has pellet in DCS but no diamond-triangle config")
        return cfg.diamond_to_motor(xyz)

    #

    @property
    def auto_correct_motors_drift(self) -> bool:
        return self._auto_correct_motors_drift

    @auto_correct_motors_drift.setter
    def auto_correct_motors_drift(self, value):
        prev, self._auto_correct_motors_drift = self._auto_correct_motors_drift, value
        self._on_property_changed(BehaviorAlgoProps.AUTO_CORRECT_MOTOR_DRIFT, value, prev)

    @property
    def shift_xyz_handler(self) -> ShiftXYZHandler:
        return self._shift_xyz_handler

    #

    def start_session(self, *, reason: str = "NA"):
        with self._thread_lock:
            return self._start_session(reason=reason)

    def _start_session(self, *, reason: str):
        if self._is_in_session:
            logger.warning("%s: start_session() called but already in session",
                           reason)
            return False

        logger.success("%s: starting new session recording ...", reason)
        EventManager.default().post_event_content(BehaviorEventKind.sessionStarting)
        self._is_in_session = True
        self._start_session_reason = reason
        self.reset_session_pellet_count()

        if self._project_info is not None:
            self._project_info.calculate_next_session_index()

        self._set_pellet_last_seen(0.0)
        self._set_triangle_last_seen(0.0)
        self._session_mouse_seen = False
        self._pellet_seen = False
        self._hands_near_pellet_seen = False

        # this is what send the trigger the enable recording at camera level,
        # but must be done after calculate next session index !!
        post_trigger_enable(self, True)

        self._diamond_triangle_offset_config = DiamondTriangleOffsetConfig.load_config(
            self._diamond_triangle_offset_config_path
        )

        self.session_starting()
        EventManager.default().post_event_content(BehaviorEventKind.sessionStarted)
        self.system_state = SystemState.tunnel
        self.property_changed(BehaviorAlgoProps.IS_IN_SESSION, True, False)
        return True

    def end_session(self, *, reason: str = "NA"):
        with self._thread_lock:
            return self._end_session(reason=reason)

    def _end_session(self, *, reason: str):
        if not self._is_in_session:
            logger.warning("%s: end_session() called but not in session (out reason: %s)",
                           reason, self._stop_session_reason)
            return False

        logger.success("%s: stopping session recording ; system_state=%s capture=%s intersession_state=%s",
                       reason, self._system_state, self._capture_status, self._intersession_state)
        self._is_in_session = False  # must be ~first, to ensure next actions/callbacks don't see it as True
        # but must be at least before self.session_ending() here after, given test_covered_load_cycle rely on that atm.
        self._stop_session_reason = reason
        EventManager.default().post_event_content(BehaviorEventKind.sessionEnding)
        post_trigger_enable(self, False)  # tells cameras processes to stop recording - ASYNC
        self.session_ending()
        EventManager.default().post_event_content(BehaviorEventKind.sessionEnded)
        EventManager.default().flush()
        self.property_changed(BehaviorAlgoProps.IS_IN_SESSION, False, True)
        return True

    def reset_session_pellet_count(self):
        self.session_pellet_count = 0

    def can_cover_pellet(self):
        return self._pellet_delivery_enabled and self._pellet_cover_enabled and not self._algo_paused

    def get_pellet_seen_age(self, perf_now: float):
        return perf_now - self._pellet_last_seen

    @property
    def pellet_seen_age(self) -> float:
        """In nbr of seconds"""
        return time.perf_counter() - self._pellet_last_seen

    @property
    def pellet_recently_seen(self):
        return time.perf_counter() - self._pellet_last_seen < self.limits.pellet_missing_time

    #

    def can_send_pellet(self):
        return not self._algo_paused

    def can_load_pellet(self):
        return self._pellet_delivery_enabled and not self.pellet_recently_seen and not self._algo_paused

    def can_release_pellet(self) -> bool:
        # self._check_date()
        if self._algo_paused:
            return False

        if self.can_cover_pellet():
            if self._is_in_session:
                return (
                    self._capture_status == CaptureProcessStatus.RECORDING
                    and self.capture_status_age >= self._recording_age_release_pellet_threshold
                    and (self.pellet_hand_uncover_distance is None or self._hands_near_pellet_seen)
                )
            return False

        return True

        # TODO: Covering for session counts is on hold due to a) not knowing actual consumed, only load cycles (
        # determining consumed happens during intersession) and b) need to determine whether said limit should
        # reset per session or per tunnel entrance (which can have multiple "sessions" when a pellet is dropped).
        # if not self.pellet_cover_enabled:
        #    if self.system_state == SystemState.tunnel:
        #        return self.session_pellet_count <= self.limits.max_pellets_per_session
        #    else:
        #        return True
        #
        # return self._is_in_session and self.session_pellet_count <= self.limits.max_pellets_per_session

    def can_perform_intersession_analysis(self):
        return self._intersession_enabled and self.session_mouse_seen

    #

    def diamond_seen(self, seen: bool):
        if seen:
            self._diamond_last_seen = time.perf_counter()

    def star_seen(self, seen: bool):
        if seen:
            self._star_last_seen = time.perf_counter()

    def triangle_seen(self, seen: bool = True):
        if self._triangle_seen != seen:
            self._triangle_seen = seen
            EventManager.default().post_event_content(BehaviorEventKind.triangleSeen, context=seen)
        if seen:
            self._set_triangle_last_seen(time.perf_counter())

    def pellet_seen(self, seen: bool = True):
        if self._pellet_seen != seen:
            self._pellet_seen = seen
            EventManager.default().post_event_content(BehaviorEventKind.pelletSeen, context=seen)
        if seen:
            self._set_pellet_last_seen(time.perf_counter())

    def pellet_loaded(self):
        self.session_pellet_count += 1

    def mouse_seen(self, seen: bool = True):
        if self._is_in_session and seen:
            prev_seen, self._session_mouse_seen = self._session_mouse_seen, True
            if not prev_seen:
                logger.verbose("Session mouse seen")
            self._on_property_changed(BehaviorAlgoProps.SESSION_MOUSE_SEEN, True, prev_seen)
            if not prev_seen:
                EventManager.default().post_event_content(BehaviorEventKind.sessionMouseSeen)

    @property
    def hands_near_pellet_seen(self):
        return self._hands_near_pellet_seen

    @property
    def pellet_hands_min_distance(self):
        return self._pellet_hands_min_distance

    @pellet_hands_min_distance.setter
    def pellet_hands_min_distance(self, value: float):
        pellet_hand_uncover_dist = self.pellet_hand_uncover_distance
        if pellet_hand_uncover_dist is not None and value <= pellet_hand_uncover_dist:
            if not self._hands_near_pellet_seen:
                logger.verbose("Hand(s) near pellet seen ; distance = %.2f mm", value)
                self._hands_near_pellet_seen = True  # must be set BEFORE doing the on_property_changed
                self._on_property_changed(
                    BehaviorAlgoProps.HANDS_NEAR_PELLET_SEEN, True, False)
        self._pellet_hands_min_distance = self._on_property_changed(
            BehaviorAlgoProps.PELLET_HANDS_DISTANCE, value, self._pellet_hands_min_distance)

    def _load_pellet_cfg(self, cfg: PelletDeliveryConfiguration):
        self.pellet_delivery_enabled = cfg.is_enabled
        self.pellet_cover_enabled = cfg.is_pellet_cover_enabled
        self.pellet_missing_time = cfg.max_pellet_missing_seconds
        self.max_pellets_per_session = cfg.max_pellets_per_session
        self.max_pellets_per_day = cfg.max_pellets_per_day
        self.intersession_pellet_shift_enabled = cfg.is_intersession_pellet_shift_enabled
        self.use_triangle_pellet_distance_too_far = cfg.use_triangle_pellet_distance_too_far
        self.triangle_pellet_diff_too_far_threshold = cfg.triangle_pellet_diff_too_far_threshold
        self.auto_correct_motors_drift = cfg.auto_correct_motors_drift
        self.pellet_hand_uncover_distance = cfg.pellet_hand_uncover_distance

    def _load_head_clamp_cfg(self, cfg: HeadClampConfiguration):
        self.min_baseline_intensity = cfg.min_baseline_intensity
        self.max_baseline_intensity = cfg.max_baseline_intensity
        self.baseline_intensity_increment = cfg.baseline_intensity_increment

        self.auto_clamp_intensity = cfg.auto_clamp_intensity
        self.auto_clamp_release_tone_freq = cfg.auto_clamp_release_tone_freq
        self.auto_clamp_release_tone_delay = cfg.auto_clamp_release_tone_delay
        self.auto_clamp_release_load_count = cfg.auto_clamp_release_load_count
        self.auto_clamp_no_activity_release_delay = cfg.auto_clamp_no_activity_release_delay

    def reset_configuration(self):
        """Reset current config to the previous loaded config (via load_configuration)"""
        prev = self._loaded_config
        if prev is not None:
            logger.notice("Resetting config to previous loaded")
            self.load_configuration(prev)

    def load_configuration(self, config: BehaviorConfiguration):
        self._loaded_config = copy.deepcopy(config)
        self._load_pellet_cfg(config.pellet_delivery)
        self._load_head_clamp_cfg(config.head_clamp)
        if self._topcam_presence is not None:
            self._topcam_presence.load_config(config.topcam_presence_detection)
        # self.auto_close_gate_on_intersession_config = config.  # not saved yet to config

    def _update_pellet_cfg(self, cfg: PelletDeliveryConfiguration):
        cfg.is_enabled = self._pellet_delivery_enabled
        cfg.is_pellet_cover_enabled = self._pellet_cover_enabled
        cfg.max_pellet_missing_seconds = self.pellet_missing_time
        cfg.max_pellets_per_session = self.max_pellets_per_session
        cfg.max_pellets_per_day = self.max_pellets_per_day
        cfg.auto_correct_motors_drift = self._auto_correct_motors_drift
        cfg.use_triangle_pellet_distance_too_far = self._use_triangle_pellet_distance_too_far
        cfg.triangle_pellet_expected_distance = self._triangle_pellet_expected_distance
        cfg.triangle_pellet_diff_too_far_threshold = self._triangle_pellet_diff_too_far_threshold
        cfg.pellet_hand_uncover_distance = self.pellet_hand_uncover_distance

    def _update_head_clamp_cfg(self, cfg: HeadClampConfiguration):
        cfg.min_baseline_intensity = self.min_baseline_intensity
        cfg.max_baseline_intensity = self.max_baseline_intensity
        cfg.baseline_intensity_increment = self.baseline_intensity_increment
        cfg.auto_clamp_intensity = self._auto_clamp_intensity
        cfg.auto_clamp_release_tone_freq = self._auto_clamp_release_tone_freq
        cfg.auto_clamp_release_tone_delay = self._auto_clamp_release_tone_delay
        cfg.auto_clamp_release_load_count = self._auto_clamp_release_load_count
        cfg.auto_clamp_no_activity_release_delay = self._auto_clamp_no_activity_release_delay

    def update_configuration(self, configuration: BehaviorConfiguration):
        self._update_pellet_cfg(configuration.pellet_delivery)
        self._update_head_clamp_cfg(configuration.head_clamp)

    def get_diamond_triangle_drifts(self, reset: bool = False) -> Optional[Offset3DTuple]:
        """Get the mean of the last seen/saved diamond triangle calculated drifts"""
        values = self._diamond_triangle_prev_drifts
        tot = reduce(operator.add, values, Offset3DTuple(0, 0, 0))
        n_vals = len(values)
        if reset:
            self._diamond_triangle_prev_drifts = []
        new_drift = Offset3DTuple(0, 0, 0) if n_vals == 0 else tot / n_vals
        if len(values) > 0:
            logger.info(
                "Motor mean drift: %s ; min=%s max=%s n_vals=%s",
                new_drift.humanize(n_digits=3),
                min(values, key=lambda v: v.distance).humanize(),
                max(values, key=lambda v: v.distance).humanize(),
                len(values),
            )
        else:
            logger.verbose("No motor drift measure available")
            # put here to minimize nbr of times we update it:
            new_drift = None
        prev, self._diamond_triangle_drift = self._diamond_triangle_drift, new_drift
        self._on_property_changed(BehaviorAlgoProps.PELLET_MOTOR_DRIFT, new_drift, prev)
        return new_drift

    def handle_diamond_triangle_offset(
        self,
        offset: Offset3DTuple,
        motor_position: Offset3DTuple,
    ):
        cfg = self._diamond_triangle_offset_config
        if cfg is None:
            return
        prev = self._diamond_triangle_drift
        drift = cfg.inference_to_motor(offset) - motor_position
        if prev is None:
            prev = Offset3DTuple(0, 0, 0)
        if __debug__:
            t_perf_now = time.perf_counter()
            if t_perf_now >= self._next_diamond_triangle_log_report:
                logger.spam("Measured motor drift: %s (prev=%s) ; pos=%s offset=%s",
                            drift.humanize(), prev.humanize(), motor_position.humanize(), offset.humanize())
                self._next_diamond_triangle_log_report = t_perf_now + 1
            if any(abs(d) >= 2 for d in drift):
                perf_now = time.perf_counter()
                if perf_now > self._diamond_triangle_last_drift_report + 1:  # max 1 / s
                    logger.debug("Measured motor drift: %s (prev=%s) ; pos=%s offset=%s",
                                 drift.humanize(), prev.humanize(), motor_position.humanize(), offset.humanize())
                    self._diamond_triangle_last_drift_report = perf_now
        self._diamond_triangle_prev_drifts.append(drift)
        if prev != drift:
            self.pellet_motor_drift_changed(drift)

    def handle_cover_pellet_offset(self, offset: Offset3DTuple):
        self._handle_check_element_distance(self._cover_pellet_distance_ctx, offset)

    def handle_release_pellet_offset(self, offset: Offset3DTuple):
        self._handle_check_element_distance(self._release_pellet_distance_ctx, offset)

    def _handle_check_element_distance(self, ctx: CheckElementDistanceContext, offset: Offset3DTuple):
        if ctx.error_detected:
            # for now: we only set once this flag, never clear it.
            return
        distance = offset.distance
        prev_distance = ctx.distance
        ctx.distance = self._on_property_changed(ctx.distance_property_name, distance, prev_distance)
        if ctx.error_way is CheckThresholdWay.TRIGGER_IF_GREATER:
            is_error = distance >= ctx.error_distance_threshold
        else:
            assert ctx.error_way is CheckThresholdWay.TRIGGER_IF_SMALLER
            is_error = distance <= ctx.error_distance_threshold
        if not is_error:
            # we might want to only unset the error_start_timestamp after some minimum duration too
            if ctx.error_start_timestamp is not None:
                ctx.error_start_timestamp = None
                logger.info("End of deviation on %s ; distance=%s",
                            ctx.distance_property_name, distance)
            return
        t_now = time.time()
        if ctx.error_start_timestamp is None:
            ctx.error_start_timestamp = t_now
            logger.warning("Detected start of %s deviation ; distance=%s threshold=%s",
                           ctx.distance_property_name, distance, ctx.error_distance_threshold)
        else:
            if t_now - ctx.error_start_timestamp >= ctx.error_min_duration_threshold:
                logger.critical("Detected %s over threshold ; distance=%.3f prev=%s threshold=%s",
                                ctx.distance_property_name, distance, prev_distance,
                                ctx.error_distance_threshold)
                ctx.error_detected = True
                prev_status = self._cover_servo_status
                new_status = CoverServoStatus(prev_status | ctx.cover_servo_status)
                self.cover_servo_status_changed(new_status)
                self._cover_servo_status = self._on_property_changed(
                    BehaviorAlgoProps.COVER_SERVO_STATUS, new_status, prev_status)

    def reset_selected_animal_counts(self, animal: AnimalSubject):
        logger.verbose("Resetting counts for animal change to %s", animal)
        self.day_pellet_count = 0
        self.pellets_presented_day = 0
        self.successful_reaches_day = 0
        self.total_pellet_count = 0
        self.pellets_presented_total = 0
        self.successful_reaches_total = 0

    def _start_day(self):
        self.day_pellet_count = 0  # consumed
        self.pellets_presented_day = 0
        self.successful_reaches_day = 0

    def _check_date(self):
        today = datetime.now().date()
        if today != self._today:
            EventManager.default().post_event_content(BehaviorEventKind.dayStarted)
            self._today = today
            self._start_day()

    @staticmethod
    def close_algorithm_handler():
        handler_thread, handler_queue = BehaviorAlgorithm._handler_thread_queue  # noqa
        if handler_queue is not None:
            BehaviorAlgorithm._handler_thread_queue = (threading.main_thread(), None)
            handler_queue.put(None)
            handler_thread.join()
            logger.info("Closed algorithm thread handler")


import atexit

atexit.register(BehaviorAlgorithm.close_algorithm_handler)
