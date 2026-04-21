import collections
import contextlib
import copy
import dataclasses
import enum
import functools
import inspect
import math
import queue
import threading
import time
from datetime import datetime, date
from functools import partial
from pathlib import Path
from typing import Optional, Tuple, ClassVar, Any, Dict, Deque, List

from typing import Callable

from typing_extensions import Self

from autotrainer.api import ApiEventKind

from autotrainer.core import ObservableObject, EventManager, post_trigger_enable, Offset3DTuple, \
    AnimalSubject, get_perf_now, calculate_std_dev_manual, ProjectInfo
from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.diamond_triangle_config import DiamondTriangleOffsetConfig
from autotrainer.core.reach_event import ReachEvent
from autotrainer.core.configuration.behavior_configuration import PelletDeliveryConfiguration, HeadClampConfiguration, \
    BehaviorConfiguration, AutoCloseGateOnIntersessionConfiguration, AutoEndSessionConfiguration, \
    BatchSessionRecordingConfiguration, HomeOnExcessiveDriftDistanceConfiguration, \
    PelletUncoverConfiguration
from autotrainer.core.video_detection import PresenceDetectionAttrs
from autotrainer.core.pose_elements import ScenePartsPresenceContext, SceneElement
from autotrainer.core.capture import CaptureProcessStatus
from autotrainer.core.interfaces import CaptureAnalysisResult, RecordingEndingReason, BehaviorAlgorithmProtocol, \
    CoverServoStatus, BehaviorAlgoEvents

from .pellet import PelletState
from .system_machine_state import SystemState
from .intersession import IntersessionState

from autotrainer.inference import PoseResponse
from autotrainer.inference.pose_algorithm import update_scene_elements_context_from_pose
from autotrainer.inference.analysis import IntersessionResponse

logger = get_verbose_logger(__name__)


@dataclasses.dataclass
class PelletUncoverContext:
    y_dcs_valid: bool = False
    start_min_y: float = math.nan  # mm
    start_y_dcs_valid_perf_c: float = math.nan  # second

    def reset(self):
        self.y_dcs_valid = False
        self.start_min_y = math.nan
        self.start_y_dcs_valid_perf_c = math.nan

    def can_uncover(self, perf_now, cfg: PelletUncoverConfiguration):
        return self.y_dcs_valid and perf_now - self.start_y_dcs_valid_perf_c >= cfg.trigger_delay


@dataclasses.dataclass
class CheckElementDistanceContext:
    distance_property_name: str
    cover_servo_status: CoverServoStatus

    expected_distance: float  # mm
    error_distance_threshold: float  # mm
    error_min_duration_threshold: float = math.inf  # unit is second

    distance: float = 0  # millimeter, current distance
    warned_bad_distance: bool = False
    error_detected: bool = False
    error_start_perf_c: Optional[float] = None


class BehaviorAlgoProps(str, enum.Enum):

    ALGO_PAUSED = 'algo_paused'

    # head-clamp / auto-clamp related:
    BASELINE_INTENSITY = 'baseline_intensity'
    HEAD_FIXATION_ENABLED = 'head_fixation_enabled'  # this is head-clamp

    # runtime context:
    PELLET_SHIFT_Y_LIMIT = 'pellet_shift_y_limit'

    DAY_PELLET_COUNT = 'day_pellet_count'  # consumed
    TOTAL_PELLET_COUNT = 'total_pellet_count'  # consumed
    DAY_PELLET_PRESENTED = 'day_pellet_presented'
    TOTAL_PELLET_PRESENTED = 'total_pellet_presented'
    DAY_PELLET_REACHES = 'day_pellet_reaches'
    TOTAL_PELLET_REACHES = 'total_pellet_reaches'
    DAY_SUCCESSFUL_REACHES = 'day_successful_reaches'
    TOTAL_SUCCESSFUL_REACHES = 'total_successful_reaches'

    INTERSESSION_ENABLED = 'intersession_enabled'  # config
    # INTERSESSION_PELLET_SHIFT_ENABLED = 'intersession_pellet_shift_enabled'

    # PELLET_DELIVERY_ENABLED = 'pellet_delivery_enabled'
    # PELLET_COVER_ENABLED = 'pellet_cover_enabled'

    # run ctx
    SESSION_PELLET_COUNT = 'session_pellet_count'
    SESSION_MOUSE_SEEN = 'session_mouse_seen'
    # NB: only updated/set once per session, once set it's kept until end of session

    AUTO_CORRECT_MOTOR_DRIFT = 'auto_correct_motor_drift'
    # PELLET_MOTOR_DRIFT = 'pellet_motor_drift'  # unused

    PELLET_UNCOVER_DELAY = 'pellet_uncover_delay'
    PELLET_UNCOVER_Y_DCS = 'pellet_uncover_y_dcs'

    COVER_SERVO_STATUS = 'cover_servo_status'  # ctx
    COVER_PELLET_DISTANCE = "cover_pellet_distance"  # cfg
    RELEASE_PELLET_DISTANCE = "release_pellet_distance"  # cfg

    # IS_IN_SESSION = 'is_in_session'  # property unused
    # INTERSESSION_STATE = 'intersession_state'  # unused
    # CAPTURE_STATUS = 'capture_status'  # unused

    # TRIANGLE_PELLET_DISTANCE = "triangle_pellet_distance"  # unused
    # PELLET_HANDS_DISTANCE = 'pellet_hands_min_distance'  # unused

    DIAMOND_TRIANGLE_CONFIG = 'diamond_triangle_config'



#

# this defines the default behavior for handling  relay of function call to the dedicated algo thread handler,
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

    base_func = func.__func__ if inspect.ismethod(func) else func

    # handle bound method vs normal function:
    @functools.wraps(base_func)
    def wrapped(*args, **kwargs):
        BehaviorAlgorithm.put_func_call(orig_func, args, kwargs, wait=wait)
    #
    wrapped._orig_func_qualname = getattr(orig_func, "__qualname__", str(orig_func))  # used by log in hardware-control
    #
    return wrapped

#


class BehaviorAlgoStatus(str, enum.Enum):
    IDLE = "idle"  # nothing running
    ACQUIRING = "acquiring"  # camera + system running, but without animal-in-device
    ANIMAL_IN_DEVICE = "animal_in_device"  # this is ACQUIRING with animal-in-device
    ANIMAL_IN_TRAINING = "animal_in_training"  # this is ANIMAL_IN_DEVICE with training behavior algo **enabled**


class BehaviorAlgorithm(ObservableObject, BehaviorAlgorithmProtocol):
    # dynamic events type hints,
    # helps IDE search/completion/type-verification:
    session_starting: BehaviorAlgoEvents.session_starting
    session_capture_ending: BehaviorAlgoEvents.session_capture_ending

    batch_analysis_starting: BehaviorAlgoEvents.batch_analysis_starting
    session_processing_starting: BehaviorAlgoEvents.session_processing_starting
    session_ending: BehaviorAlgoEvents.session_ending
    batch_analysis_ending: BehaviorAlgoEvents.batch_analysis_ending

    cover_servo_status_changed: BehaviorAlgoEvents.cover_servo_status_changed  # unused

    # NB:
    # these events receive as single param/arg the **increment** applied to the previous value (whatever it was):
    pellets_presented_evt: BehaviorAlgoEvents.pellets_presented_evt
    pellets_consumed_evt: BehaviorAlgoEvents.pellets_consumed_evt
    successful_reaches_evt: BehaviorAlgoEvents.successful_reaches_evt
    total_reaches_evt: BehaviorAlgoEvents.total_reaches_evt

    #

    _thread_locals: ClassVar[threading.local] = threading.local()
    _handler_thread_queue: ClassVar[Tuple[threading.Thread, Optional[queue.Queue]]] = (threading.current_thread(), None)
    _no_handler_thread: ClassVar[Optional[bool]] = False

    def __init__(
        self,
        *,
        project_info: Optional[ProjectInfo] = None,
        diamond_triangle_offset_config_path: Optional[Path] = None,
        topcam_presence: Optional[PresenceDetectionAttrs] = None,
    ):
        super().__init__(event_names=tuple(attr for attr in dir(BehaviorAlgoEvents) if not attr.startswith('_')))

        self._event_manager = EventManager.default()  # for posting events

        self._thread_lock = threading.RLock()
        self._project_info = project_info
        self._status = BehaviorAlgoStatus.IDLE

        self._active_config = BehaviorConfiguration()
        self._loaded_config: Optional[BehaviorConfiguration] = None

        self._head_fixation_enabled = False  # NB: not saved in config
        self._clean_raw_data_on_inactive_session = False

        self._parts_pres_ctx_any_cam = ScenePartsPresenceContext()
        self._parts_pres_ctx_all_cams = ScenePartsPresenceContext()

        # now using self._active_config.head_clamp mainly,
        # and also:
        self._baseline_intensity = self._active_config.head_clamp.baseline_intensity

        # NB: not saved in config:
        self._recording_age_release_pellet_threshold = 0.25

        self._recording_prebuffer_duration = 0

        # active/live context:
        self._algo_paused = False
        self._algo_paused_perf_t = -math.inf
        self._is_in_session = False
        self._session_started_perf_c = -math.inf
        self._start_session_reason = "NA"
        self._stop_session_reason = RecordingEndingReason.NA

        self._session_mouse_seen = False
        self._pellet_hands_min_distance: float = math.inf
        self._mouse_seen_last_perf_c = -math.inf
        self._triangle_pellet_last_offset = Offset3DTuple(math.nan, math.nan, math.nan)
        self._next_diamond_triangle_log_report = -math.inf

        self._uncover_ctx = PelletUncoverContext()

        self._system_state = SystemState.cage
        self._intersession_state = IntersessionState.idle
        self._capture_status = CaptureProcessStatus.UNKNOWN
        self._last_capture_status_change_perf_c = -math.inf

        # self.max_pellets_per_headfix_session: int = 10  # unused

        self._pellet_shift_y_limit: Optional[float] = None

        self._session_pellet_loaded_count = 0  # loaded

        self._pellet_counts_day_date = date.today()
        self._pellets_consumed_day = 0  # consumed
        self._pellets_consumed_total = 0  # consumed
        self._pellets_presented_day: int = 0
        self._pellets_presented_total: int = 0
        self._reaches_day: int = 0
        self._reaches_total: int = 0
        self._successful_reaches_day: int = 0
        self._successful_reaches_total: int = 0

        self._previous_intersession_analysis_rsp: Optional[Tuple[ProjectInfo, IntersessionResponse]] = None

        self._cover_servo_status = CoverServoStatus.OK

        self._topcam_presence: Optional[PresenceDetectionAttrs] = topcam_presence

        if diamond_triangle_offset_config_path is None:
            diamond_triangle_offset_config_path = DiamondTriangleOffsetConfig.DEFAULT_CONFIG_PATH
        self._diamond_triangle_offset_config_path = diamond_triangle_offset_config_path

        self._diamond_triangle_offset_config: Optional[DiamondTriangleOffsetConfig] = None

        self._diamond_triangle_drift: Optional[Offset3DTuple] = None
        self._diamond_triangle_prev_drifts: Deque[Offset3DTuple] = collections.deque(maxlen=150)
        self._diamond_triangle_next_drift_report = -math.inf

        self._cover_pellet_distance_ctx = CheckElementDistanceContext(
            distance_property_name=BehaviorAlgoProps.COVER_PELLET_DISTANCE,
            expected_distance=12,
            error_distance_threshold=2,
            error_min_duration_threshold=3,
            cover_servo_status=CoverServoStatus.COVER_POSITION_ERROR,
        )
        self._release_pellet_distance_ctx = CheckElementDistanceContext(
            distance_property_name=BehaviorAlgoProps.RELEASE_PELLET_DISTANCE,
            expected_distance=15,
            error_distance_threshold=2,
            error_min_duration_threshold=3,
            cover_servo_status=CoverServoStatus.RELEASE_POSITION_ERROR,
        )
        #
        self._check_start_thread(thread_lock=self._thread_lock)
        #
        self._today = None  # only used in check_date, unused, atm
        # self._start_day()
        #

    @classmethod
    def _check_start_thread(cls: "BehaviorAlgorithm", *, thread_lock: threading.RLock):
        if cls._no_handler_thread:
            return
        _, handler_queue = cls._handler_thread_queue
        if handler_queue is None:
            logger.info("Creating algo handler thread ..")
            handler_queue = queue.Queue(maxsize=64)
            handler_thread = threading.Thread(
                target=cls._handler_thread_run, args=(handler_queue, thread_lock),
                daemon=True,
                name="AlgoHandler",
            )
            cls._handler_thread_queue = (handler_thread, handler_queue)  # noqa
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

    def relay_func(func=None, *, wait: bool=_DEFAULT_ALGO_HANDLER_THREAD_CALL_SYNC_WAIT_MODE):
        """Decorator for marking a function/method as having to be relayed to our algo dedicated thread"""
        if func is None:
            return partial(_relay_func, wait=wait)
        return _relay_func(func, wait=wait)

    @classmethod
    def _handler_thread_run(cls: "BehaviorAlgorithm", input_queue: queue.Queue, thread_lock):
        logger.verbose("Running for handling/executing all algo decision/transition ..")
        prev_perf_c_report = time.perf_counter()
        tot_msgs = 0
        prev_tot_msgs = None
        while True:
            p_now = time.perf_counter()
            if p_now - prev_perf_c_report > 5:
                if tot_msgs > 0 or prev_tot_msgs != tot_msgs:
                    logger.debug("%.1f msgs/s", tot_msgs / (p_now - prev_perf_c_report))
                    prev_tot_msgs = tot_msgs
                    tot_msgs = 0
                else:
                    prev_tot_msgs = tot_msgs
                prev_perf_c_report = p_now
            try:
                raw = input_queue.get(timeout=1)
            except queue.Empty:
                continue
            if raw is None:
                input_queue.task_done()
                break
            tot_msgs += 1
            func, args, kwargs, event = raw
            try:
                with thread_lock:
                    func(*args) if kwargs is None else func(*args, **kwargs)
            except Exception as err:
                logger.exception("Failed executing %s(%s, %s): %s", func, args, kwargs, err)
                # NB: what to do else ?
                # this is a pretty critical situation given the related function might be itself critical.
                # TODO: maybe relay a flag/msg/error to the main thread for display purpose ?
                # actually this should even trigger a restart of the application.
            if event is not None:
                event.set()
            input_queue.task_done()
        logger.debug("Exiting ; left queue_size=%s", input_queue.qsize())

    @classmethod
    def relay_transitions(cls: "BehaviorAlgorithm", machine_transitions: Any,
                          *, wait: bool=_DEFAULT_ALGO_HANDLER_THREAD_CALL_SYNC_WAIT_MODE):
        """Relay all transition triggers of the given machine_transitions instance to the algo dedicated thread"""
        for trans in machine_transitions.transitions:
            trig = trans['trigger']
            if trig is not None:
                if callable(trig):
                    trig = trig.__name__
                meth = getattr(machine_transitions, trig)
                wrapped = cls.relay_func(meth, wait=wait)
                logger.spam("relaying transition %s -> %s", trig, wrapped)
                setattr(machine_transitions, trig, wrapped)

    @classmethod
    def put_func_call(
        cls: "BehaviorAlgorithm",
        func: Callable,
        args: Tuple[Any, ...] = (),
        kwargs: Optional[Dict]=None,
        *,
        wait: bool=_DEFAULT_ALGO_HANDLER_THREAD_CALL_SYNC_WAIT_MODE,
    ):
        """Put a function call request to the algo dedicated thread, and eventually wait on its completion.
        See also `BehaviorAlgorithm.set_put_func_call_mode`.
        """
        handler_thread, handler_queue = BehaviorAlgorithm._handler_thread_queue
        if threading.current_thread() is handler_thread or handler_queue is None or cls._no_handler_thread:
            # logger.debug("%s: in-place execution ; already in system msg handler thread", func)
            func(*args) if kwargs is None else func(*args, **kwargs)
        else:
            t_local_sync: Optional[bool] = getattr(cls._thread_locals, "sync_call_mode", None)
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
    def project(self) -> Optional[ProjectInfo]:
        return self._project_info

    @project.setter
    def project(self, project: ProjectInfo):
        self._project_info = project

    @property
    def status(self) -> BehaviorAlgoStatus:
        return self._status

    @status.setter
    def status(self, value: BehaviorAlgoStatus):
        prev, self._status = self._status, value
        # self._on_property_changed(self.Props.STATUS, value, prev)

    @property
    def algo_paused(self) -> bool:
        return self._algo_paused

    @algo_paused.setter
    def algo_paused(self, value: bool):
        prev, self._algo_paused = self._algo_paused, value
        if value == prev:
            return
        self._event_manager.post_event_content(
            ApiEventKind.algorithmPause if value
            else ApiEventKind.algorithmResume)
        if value and not prev:
            self._algo_paused_perf_t = get_perf_now()
        self._on_property_changed(BehaviorAlgoProps.ALGO_PAUSED, value, prev)

    @property
    def top_camera_presence_detection(self) -> Optional[PresenceDetectionAttrs]:
        return self._topcam_presence

    @top_camera_presence_detection.setter
    def top_camera_presence_detection(self, value: Optional[PresenceDetectionAttrs]):
        self._topcam_presence = value

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
        # self._on_property_changed(BehaviorAlgoProps.INTERSESSION_STATE, value, prev)

    @property
    def capture_status(self) -> CaptureProcessStatus:
        return self._capture_status

    @capture_status.setter
    def capture_status(self, value: CaptureProcessStatus):
        prev, self._capture_status = self._capture_status, value
        self._last_capture_status_change_perf_c = get_perf_now()
        # self._on_property_changed(BehaviorAlgoProps.CAPTURE_STATUS, value, prev)  # property changed event unused atm

    @property
    def capture_status_age(self) -> float:
        """Capture status age as number of seconds"""
        return get_perf_now() - self._last_capture_status_change_perf_c

    @property
    def recording_age_release_pellet_threshold(self) -> float:
        """Desired delay to wait once camera recording-started is detected, to then after release the pellet"""
        return self._recording_age_release_pellet_threshold

    @property
    def is_in_session(self) -> bool:
        """Is in capture/recording session"""
        return self._is_in_session

    @property
    def is_in_session_age(self) -> float:
        return get_perf_now() - self._session_started_perf_c

    @property
    def auto_close_gate_on_intersession_config(self) -> AutoCloseGateOnIntersessionConfiguration:
        return self._active_config.auto_close_gate_on_intersession

    @property
    def pellet_delivery_enabled(self) -> bool:
        return self._active_config.pellet_delivery.is_enabled

    @pellet_delivery_enabled.setter
    def pellet_delivery_enabled(self, value: bool):
        # cfg = self._active_config.pellet_delivery
        # prev, cfg.is_enabled = cfg.is_enabled, value
        self._active_config.pellet_delivery.is_enabled = value
        # self._on_property_changed(BehaviorAlgoProps.PELLET_DELIVERY_ENABLED, value, prev)

    @property
    def pellet_cover_enabled(self) -> bool:
        return self._active_config.pellet_delivery.is_pellet_cover_enabled

    @pellet_cover_enabled.setter
    def pellet_cover_enabled(self, value: bool):
        # cfg = self._active_config.pellet_delivery
        self._active_config.pellet_delivery.is_pellet_cover_enabled = value
        # prev, cfg.is_pellet_cover_enabled = cfg.is_pellet_cover_enabled, value
        # self._on_property_changed(BehaviorAlgoProps.PELLET_COVER_ENABLED, value, prev)

    @property
    def uncover_context(self) -> PelletUncoverContext:
        return self._uncover_ctx

    @property
    def pellet_shift_y_limit(self) -> Optional[float]:
        return self._pellet_shift_y_limit

    @pellet_shift_y_limit.setter
    def pellet_shift_y_limit(self, value: Optional[float]):
        prev, self._pellet_shift_y_limit = self._pellet_shift_y_limit, value
        self._on_property_changed(BehaviorAlgoProps.PELLET_SHIFT_Y_LIMIT, value, prev)

    @property
    def pellet_uncover_y_dcs(self) -> float:
        return self._active_config.pellet_uncover.min_y_dcs

    @pellet_uncover_y_dcs.setter
    def pellet_uncover_y_dcs(self, value: float):
        cfg = self._active_config.pellet_uncover
        prev, cfg.min_y_dcs = cfg.min_y_dcs, value
        self._on_property_changed(BehaviorAlgoProps.PELLET_UNCOVER_Y_DCS, value, prev)

    @property
    def pellet_uncover_delay(self) -> float:
        return self._active_config.pellet_uncover.trigger_delay

    @pellet_uncover_delay.setter
    def pellet_uncover_delay(self, value: float):
        cfg = self._active_config.pellet_uncover
        prev, cfg.trigger_delay = cfg.trigger_delay, value
        self._on_property_changed(BehaviorAlgoProps.PELLET_UNCOVER_DELAY, value, prev)

    @property
    def pellet_missing_time(self) -> float:
        return self._active_config.pellet_delivery.max_pellet_missing_seconds

    @pellet_missing_time.setter
    def pellet_missing_time(self, value: float):
        self._active_config.pellet_delivery.max_pellet_missing_seconds = value

    @property
    def triangle_missing_time(self) -> float:  # alias/mirror value of pellet_missing_time
        return self.pellet_missing_time

    @property
    def intersession_enabled(self) -> bool:
        return self._active_config.pellet_delivery.is_intersession_analysis_enabled

    @intersession_enabled.setter
    def intersession_enabled(self, value: bool):
        cfg = self._active_config.pellet_delivery
        prev, cfg.is_intersession_analysis_enabled = cfg.is_intersession_analysis_enabled, value
        self._on_property_changed(BehaviorAlgoProps.INTERSESSION_ENABLED, value, prev)

    @property
    def intersession_pellet_shift_enabled(self) -> bool:
        return self._active_config.pellet_delivery.is_intersession_pellet_shift_enabled

    @intersession_pellet_shift_enabled.setter
    def intersession_pellet_shift_enabled(self, value: bool):
        self._active_config.pellet_delivery.is_intersession_pellet_shift_enabled = value
        # prev, self._intersession_pellet_shift_enabled = self._intersession_pellet_shift_enabled, value
        # self._on_property_changed(BehaviorAlgoProps.INTERSESSION_PELLET_SHIFT_ENABLED, value, prev)

    @property
    def head_fixation_enabled(self) -> bool:
        # NB: not saved in config
        return self._head_fixation_enabled

    @head_fixation_enabled.setter
    def head_fixation_enabled(self, value: bool):
        # NB: not saved in config
        prev, self._head_fixation_enabled = self._head_fixation_enabled, value
        if prev != self._head_fixation_enabled:
            logger.info("auto-clamp enabled changed to: %s", self._head_fixation_enabled)
            self._on_property_changed(BehaviorAlgoProps.HEAD_FIXATION_ENABLED, value, prev)
            self._event_manager.post_event_content(ApiEventKind.autoClampEnabledChanged, data=dict(is_enabled=value))

    @property
    def clean_raw_data_on_inactive_session(self):
        return self._clean_raw_data_on_inactive_session

    @clean_raw_data_on_inactive_session.setter
    def clean_raw_data_on_inactive_session(self, value):
        self._clean_raw_data_on_inactive_session = value

    @property
    def baseline_intensity(self) -> float:
        """Head magnet "baseline" intensity ; set from animal/subject"""
        return self._baseline_intensity

    @baseline_intensity.setter
    def baseline_intensity(self, value: float):
        prev, self._baseline_intensity = self._baseline_intensity, value
        if value != prev:
            self._on_property_changed(BehaviorAlgoProps.BASELINE_INTENSITY, value, prev)

    @property
    def head_clamp_config(self) -> HeadClampConfiguration:
        """The whole HeadClamp config, can be modified in place,
        although no event/change cb, if any is configured on behavior algo, will be emitted in that case"""
        return self._active_config.head_clamp

    @property
    def auto_clamp_intensity(self) -> float:
        return self._active_config.head_clamp.auto_clamp_intensity

    @auto_clamp_intensity.setter
    def auto_clamp_intensity(self, value: float):
        cfg = self._active_config.head_clamp
        prev, cfg.auto_clamp_intensity = cfg.auto_clamp_intensity, value
        if value != prev:
            # prop unused
            #     self._on_property_changed(BehaviorAlgoProps.AUTO_CLAMP_INTENSITY, value, prev)
            self._event_manager.post_event_content(
                ApiEventKind.autoClampIntensityChanged, data=dict(intensity=value))

    @property
    def auto_clamp_release_tone_freq(self) -> int:
        """Frequency of the tone played when auto-clamp is released in Hz"""
        return self._active_config.head_clamp.auto_clamp_release_tone_freq

    @auto_clamp_release_tone_freq.setter
    def auto_clamp_release_tone_freq(self, value: int):
        cfg = self._active_config.head_clamp
        prev, cfg.auto_clamp_release_tone_freq = cfg.auto_clamp_release_tone_freq, value
        if value != prev:
            # prop unused
            # self._on_property_changed("auto_clamp_release_tone_freq", value, prev)
            self._event_manager.post_event_content(ApiEventKind.autoClampReleaseToneFreqChanged,
                                                   data=dict(frequency=value))

    @property
    def auto_clamp_release_tone_delay(self) -> float:
        return self._active_config.head_clamp.auto_clamp_release_tone_delay

    @auto_clamp_release_tone_delay.setter
    def auto_clamp_release_tone_delay(self, value: float):
        cfg = self._active_config.head_clamp
        prev, cfg.auto_clamp_release_tone_delay = cfg.auto_clamp_release_tone_delay, value
        if value != prev:
            # prop unused
            # self._on_property_changed("auto_clamp_release_tone_delay", value, prev)
            self._event_manager.post_event_content(ApiEventKind.autoClampReleaseDelayChanged,
                                                   data=dict(delay=value))

    @property
    def auto_clamp_release_load_count(self) -> int:
        return self._active_config.head_clamp.auto_clamp_release_load_count

    @auto_clamp_release_load_count.setter
    def auto_clamp_release_load_count(self, value: int):
        self._active_config.head_clamp.auto_clamp_release_load_count = value

    @property
    def auto_clamp_no_activity_release_delay(self):
        return self._active_config.head_clamp.auto_clamp_no_activity_release_delay

    @auto_clamp_no_activity_release_delay.setter
    def auto_clamp_no_activity_release_delay(self, value):
        self._active_config.head_clamp.auto_clamp_no_activity_release_delay = value

    @property
    def auto_clamp_before_reengage_delay(self) -> float:
        return self._active_config.head_clamp.before_reengage_delay

    @auto_clamp_before_reengage_delay.setter
    def auto_clamp_before_reengage_delay(self, value):
        self._active_config.head_clamp.before_reengage_delay = value

    #

    @property
    def record_prebuffer_duration(self) -> float:
        return self._recording_prebuffer_duration

    @record_prebuffer_duration.setter
    def record_prebuffer_duration(self, value):
        self._recording_prebuffer_duration = value

    #

    @property
    def triangle_last_seen(self) -> float:  # only used by test atm
        return self._parts_pres_ctx_any_cam.present_last_perf_c.get(SceneElement.Triangle, -math.inf)

    @property
    def triangle_recently_seen(self) -> bool:
        # only used in tests and a log
        return self._parts_pres_ctx_any_cam.get_recently_seen(
            SceneElement.Triangle,
            self.limits.triangle_missing_time,
            perf_now=get_perf_now(),
        )

    @property
    def diamond_recently_seen(self) -> bool:
        # only used in test
        return self._parts_pres_ctx_any_cam.get_recently_seen(
            SceneElement.Diamond,
            self.limits.triangle_missing_time,
            perf_now=get_perf_now(),
        )

    @property
    def triangle_pellet_offset(self) -> Offset3DTuple:  # not used
        return self._triangle_pellet_last_offset

    @triangle_pellet_offset.setter
    def triangle_pellet_offset(self, value):
        prev, self._triangle_pellet_last_offset = self._triangle_pellet_last_offset, value
        # self._on_property_changed(BehaviorAlgoProps.TRIANGLE_PELLET_DISTANCE, self.triangle_pellet_distance,
        #                           prev.distance)

    @property
    def triangle_pellet_distance(self) -> float:
        return self._triangle_pellet_last_offset.distance

    @property
    def use_triangle_pellet_distance_too_far(self) -> bool:
        return self._active_config.pellet_delivery.use_triangle_pellet_distance_too_far

    @use_triangle_pellet_distance_too_far.setter
    def use_triangle_pellet_distance_too_far(self, value):
        self._active_config.pellet_delivery.use_triangle_pellet_distance_too_far = value

    @property
    def triangle_pellet_expected_distance(self):
        return self._active_config.pellet_delivery.triangle_pellet_expected_distance

    @triangle_pellet_expected_distance.setter
    def triangle_pellet_expected_distance(self, value):
        self._active_config.pellet_delivery.triangle_pellet_expected_distance = value

    @property
    def triangle_pellet_diff_too_far_threshold(self) -> float:
        """Diff threshold above which pellet is considered "too-far" from triangle.
        That is if abs(current_distance - expected_distance) >= diff_threshold -> too far
        """
        return self._active_config.pellet_delivery.triangle_pellet_diff_too_far_threshold

    @triangle_pellet_diff_too_far_threshold.setter
    def triangle_pellet_diff_too_far_threshold(self, value: float):
        self._active_config.pellet_delivery.triangle_pellet_diff_too_far_threshold = value

    def is_triangle_pellet_distance_too_far(self) -> bool:
        """Check if triangle is too far from pellet according to triangle_pellet_expected_distance & triangle_pellet_diff_too_far_threshold"""
        cfg = self._active_config.pellet_delivery
        last_dist_diff = abs(self.triangle_pellet_distance - cfg.triangle_pellet_expected_distance)
        p_now = get_perf_now()
        return (
            self.is_part_recently_seen(SceneElement.Pellet, perf_now=p_now)
            and self.is_part_recently_seen(SceneElement.Triangle, perf_now=p_now)
            and last_dist_diff >= cfg.triangle_pellet_diff_too_far_threshold
        )

    # counts

    def _check_pellet_counts_day_date(self):
        today = date.today()
        if today != self._pellet_counts_day_date:
            logger.verbose("resetting pellet day counts to 0")
            self._pellet_counts_day_date = today
            self.pellets_presented_day = 0
            self.pellet_reaches_day = 0
            self.pellet_consumed_day = 0
            self.successful_reaches_day = 0

    @property
    def pellet_consumed_day(self) -> int:
        self._check_pellet_counts_day_date()
        return self._pellets_consumed_day

    @pellet_consumed_day.setter
    def pellet_consumed_day(self, value: int):
        prev_value, self._pellets_consumed_day = self._pellets_consumed_day, value
        self._on_property_changed(BehaviorAlgoProps.DAY_PELLET_COUNT, value, prev_value)

    @property
    def pellet_consumed_total(self) -> int:
        return self._pellets_consumed_total

    @pellet_consumed_total.setter
    def pellet_consumed_total(self, value: int):
        prev, self._pellets_consumed_total = self._pellets_consumed_total, value
        self._on_property_changed(BehaviorAlgoProps.TOTAL_PELLET_COUNT, value, prev)

    @property
    def session_pellet_loaded_count(self) -> int:
        return self._session_pellet_loaded_count

    @session_pellet_loaded_count.setter
    def session_pellet_loaded_count(self, value):
        prev, self._session_pellet_loaded_count = self._session_pellet_loaded_count, value
        self._on_property_changed(BehaviorAlgoProps.SESSION_PELLET_COUNT, value, prev)  # property unused

    def increase_pellets_consumed(self, increment: int = 1):
        self.pellet_consumed_day += increment
        self.pellet_consumed_total += increment
        if increment:
            self.pellets_consumed_evt(increment)
            self._event_manager.post_event_content(
                ApiEventKind.pelletConsumedCountChanged,
                data=dict(change=increment, count=self._pellets_consumed_total))
            self._event_manager.post_event_content(
                ApiEventKind.dayPelletConsumedCountChanged,
                data=dict(change=increment, count=self._pellets_consumed_day))

    @property
    def pellets_presented_day(self):
        self._check_pellet_counts_day_date()
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
        self._on_property_changed(BehaviorAlgoProps.TOTAL_PELLET_PRESENTED, value, prev)

    def increase_pellets_presented(self, increment: int = 1):
        self.pellets_presented_day += increment
        self.pellets_presented_total += increment
        if increment:
            self.pellets_presented_evt(increment)
            self._event_manager.post_event_content(
                ApiEventKind.pelletPresentedCountChanged,
                data=dict(change=increment, count=self._pellets_presented_total))
            self._event_manager.post_event_content(
                ApiEventKind.dayPelletPresentedCountChanged,
                data=dict(change=increment, count=self._pellets_presented_day))

    @property
    def pellet_reaches_day(self):
        self._check_pellet_counts_day_date()
        return self._reaches_day

    @pellet_reaches_day.setter
    def pellet_reaches_day(self, value):
        prev, self._reaches_day = self._reaches_day, value
        self._on_property_changed(BehaviorAlgoProps.DAY_PELLET_REACHES, value, prev)

    @property
    def pellet_reaches_total(self):
        return self._reaches_total

    @pellet_reaches_total.setter
    def pellet_reaches_total(self, value):
        prev, self._reaches_total = self._reaches_total, value
        self._on_property_changed(BehaviorAlgoProps.TOTAL_PELLET_REACHES, value, prev)

    def increase_pellet_total_reaches(self, increment: int = 1):
        self.pellet_reaches_day += increment
        self.pellet_reaches_total += increment
        if increment:
            self.total_reaches_evt(increment)
            self._event_manager.post_event_content(
                ApiEventKind.reachCountChanged,
                data=dict(change=increment, count=self._reaches_total))
            self._event_manager.post_event_content(
                ApiEventKind.dayReachCountChanged,
                data=dict(change=increment, count=self._reaches_day))

    @property
    def successful_reaches_day(self):
        self._check_pellet_counts_day_date()
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
        self._on_property_changed(BehaviorAlgoProps.TOTAL_SUCCESSFUL_REACHES, value, prev)

    def increase_successful_reaches(self, increment: int = 1):
        self.successful_reaches_day += increment
        self.successful_reaches_total += increment
        if increment:
            self.successful_reaches_evt(increment)
            self._event_manager.post_event_content(
                ApiEventKind.successfulReachesCountChanged,
                data=dict(change=increment, count=self._successful_reaches_total))
            self._event_manager.post_event_content(
                ApiEventKind.daySuccessfulReachesCountChanged,
                data=dict(change=increment, count=self._successful_reaches_day))
    #

    @property
    def cover_servo_status(self) -> CoverServoStatus:
        return self._cover_servo_status

    @cover_servo_status.setter
    def cover_servo_status(self, status: CoverServoStatus):
        prev, self._cover_servo_status = self._cover_servo_status, status
        if status is CoverServoStatus.OK:
            logger.notice("Set cover servo status to %s", status)
        self._on_property_changed(BehaviorAlgoProps.COVER_SERVO_STATUS, status, prev)

    #

    @property
    def diamond_triangle_config(self) -> Optional[DiamondTriangleOffsetConfig]:
        return self._diamond_triangle_offset_config

    @diamond_triangle_config.setter
    def diamond_triangle_config(self, value):
        prev, self._diamond_triangle_offset_config = self._diamond_triangle_offset_config, value
        self._on_property_changed(BehaviorAlgoProps.DIAMOND_TRIANGLE_CONFIG, value, prev)

    def load_diamond_triangle_config(self, path: Optional[Path] = None):
        if path is None:
            path = self._diamond_triangle_offset_config_path
        return DiamondTriangleOffsetConfig.load_config(path)

    def reload_diamond_triangle_config(self, path: Optional[Path] = None):
        self.diamond_triangle_config = self.load_diamond_triangle_config(path)

    @property
    def diamond_triangle_drift(self) -> Optional[Offset3DTuple]:
        return self._diamond_triangle_drift

    @property
    def diamond_triangle_offset_config_path(self) -> Optional[Path]:
        return self._diamond_triangle_offset_config_path

    #

    @property
    def auto_end_session_config(self) -> AutoEndSessionConfiguration:
        return self._active_config.auto_end_session

    @property
    def batch_session_recording_config(self) -> BatchSessionRecordingConfiguration:
        return self._active_config.batch_session_recording

    @property
    def auto_correct_motors_drift(self) -> bool:
        return self._active_config.pellet_delivery.auto_correct_motors_drift

    @auto_correct_motors_drift.setter
    def auto_correct_motors_drift(self, value):
        cfg = self._active_config.pellet_delivery
        prev, cfg.auto_correct_motors_drift = cfg.auto_correct_motors_drift, value
        self._on_property_changed(BehaviorAlgoProps.AUTO_CORRECT_MOTOR_DRIFT, value, prev)

    @property
    def any_cams_scene_parts_presence_context(self) -> ScenePartsPresenceContext:
        return self._parts_pres_ctx_any_cam

    @property
    def all_cams_scene_parts_presence_context(self) -> ScenePartsPresenceContext:
        return self._parts_pres_ctx_all_cams

    #

    def start_session(self, *, reason: str = "NA"):
        with self._thread_lock:
            return self._start_capture_session(reason=reason)

    def _start_capture_session(self, *, reason: str):
        if self._is_in_session:
            logger.warning("%s: start_session() called but already in session", reason)
            return False
        if self._algo_paused:
            logger.error("%s: refusing start session when algo paused", reason)
            return False

        logger.success("%s: starting new session recording ...", reason)
        self._is_in_session = True
        self._session_started_perf_c = get_perf_now()
        self._start_session_reason = reason
        self.reset_session_pellet_count()

        project = self._project_info
        if project is not None:  # can there be session capture without project_info actually ?
            project.calculate_next_session_index()
            self._event_manager.post_event_content(
                ApiEventKind.projectSessionChanged,
                data=dict(root=project.root, session=project.session),
            )

        # ensure we look at their state on start:
        self._session_mouse_seen = False
        self._uncover_ctx.reset()  # always

        # this is what send the trigger the enable recording at camera level,
        # but must be done after calculate next session index !!
        post_trigger_enable(self, True)

        self.session_starting()

        self._event_manager.post_event_content(ApiEventKind.trialStarted)

        return True

    def end_capture_session(self, *, reason: RecordingEndingReason = RecordingEndingReason.NA):
        with self._thread_lock:
            return self._end_capture_session(reason=reason)

    def _end_capture_session(self, *, reason: RecordingEndingReason):
        if not self._is_in_session:
            logger.warning("%s: end_session() called but not in session (out reason: %s)",
                           reason, self._stop_session_reason)
            return False
        logger.success("%s: stopping session recording ; system_state=%s capture=%s intersession_state=%s",
                       reason, self._system_state, self._capture_status, self._intersession_state)
        self._is_in_session = False  # must be ~first, to ensure next actions/callbacks don't see it as True
        # but must be at least before self.session_ending() here after, given test_covered_load_cycle rely on that atm.
        self._stop_session_reason = reason
        post_trigger_enable(self, False)  # tells cameras processes to stop recording - ASYNC
        self.session_capture_ending(reason)
        self._event_manager.flush()
        self.get_diamond_triangle_drifts(show_log=True)  # convenience to log current values
        self._event_manager.post_event_content(
            ApiEventKind.trialCaptureEnded, data=dict(reason=reason))
        return True

    def end_session(self, result: CaptureAnalysisResult):
        logger.notice("session processing end: %s", result)
        self._event_manager.post_event_content(
            ApiEventKind.trialEnded, data=dict(result=result))
        self.session_ending(result)

    def reset_session_pellet_count(self):
        self.session_pellet_loaded_count = 0

    @property
    def pellet_presence_age(self) -> float:
        """Return value in seconds unit"""
        return self._parts_pres_ctx_any_cam.get_presence_age(SceneElement.Pellet)

    @property
    def pellet_recently_seen(self):
        return self._parts_pres_ctx_any_cam.get_recently_seen(
            SceneElement.Pellet, self.limits.pellet_missing_time,
            perf_now=get_perf_now(),
        )

    def is_part_recently_seen(self, part: str, *, use_any_cam: bool=False, perf_now: Optional[float]=None) -> bool:
        ctx = self._parts_pres_ctx_any_cam if use_any_cam else self._parts_pres_ctx_all_cams
        if perf_now is None:
            perf_now = get_perf_now()
        return ctx.get_recently_seen(part, self.limits.pellet_missing_time, perf_now=perf_now)

    def is_pellet_recently_seen(self, *, use_any_cam: bool=False, perf_now: Optional[float]=None) -> bool:
        return self.is_part_recently_seen(SceneElement.Pellet, use_any_cam=use_any_cam, perf_now=perf_now)

    #

    def can_send_pellet(self):
        if self._status is not BehaviorAlgoStatus.ANIMAL_IN_TRAINING:
            return False
        return self._active_config.pellet_delivery.is_enabled and not self._algo_paused

    def would_load_pellet(
        self,
        *,
        delivery_cfg: Optional[PelletDeliveryConfiguration] = None,
        pellet_state: PelletState = PelletState.monitoring,
        use_any_cam: bool=False,
        perf_now: Optional[float]=None,
    ) -> bool:
        """Say whether a load-pellet is needed or not, basically if pellet is missing confirmed"""
        if perf_now is None:
            perf_now = get_perf_now()
        pellet_missing = (
                not self.is_part_recently_seen(SceneElement.Pellet, use_any_cam=use_any_cam)
            and (self.is_part_recently_seen(SceneElement.Triangle, use_any_cam=use_any_cam)
                 or (pellet_state == PelletState.monitoring
                     and self.is_part_recently_seen(SceneElement.Star, use_any_cam=use_any_cam)))
        )
        if pellet_missing:
            # logger.verbose("BehaviorAlgo.can_load_pellet: pellet missing")
            return True
        # NB: todo: pellet_too_far should probably not immediately trigger a load-pellet...
        # first a tunnel FAN can be executed..
        # then maybe normal pellet-load (with pellet fully mussing) will be triggered
        pellet_too_far = (
            (delivery_cfg is None or delivery_cfg.use_triangle_pellet_distance_too_far)
             and pellet_state == PelletState.monitoring
             and self.is_triangle_pellet_distance_too_far()
        )
        if pellet_too_far:
            # logger.verbose("BehaviorAlgo.can_load_pellet: pellet too far")
            return True
        return False

    def can_load_pellet(self, *, pellet_state: PelletState = PelletState.monitoring, use_any_cam: bool=False) -> bool:
        """Say if a pellet can and must be loaded"""
        # is more has_to_load_pellet()
        if self._status is not BehaviorAlgoStatus.ANIMAL_IN_TRAINING:
            return False
        cfg = self._active_config.pellet_delivery
        if not cfg.is_enabled or self._algo_paused:
            return False
        return self.would_load_pellet(delivery_cfg=cfg, pellet_state=pellet_state, use_any_cam=use_any_cam)

    def can_cover_pellet(self) -> bool:
        """Say if cover-pellet is enabled"""
        if self._status is not BehaviorAlgoStatus.ANIMAL_IN_TRAINING:
            return False
        cfg = self._active_config.pellet_delivery
        return cfg.is_enabled and cfg.is_pellet_cover_enabled and not self._algo_paused

    def can_release_pellet(self) -> bool:
        """Say if algo should release pellet"""
        # self._check_date()
        if self._status is not BehaviorAlgoStatus.ANIMAL_IN_TRAINING:
            return False
        if self._algo_paused:
            return False
        cfg = self._active_config.pellet_delivery
        uncov_cfg = self._active_config.pellet_uncover
        ctx = self._uncover_ctx
        if self.can_cover_pellet():
            if self._is_in_session:
                p_now = get_perf_now()
                return (
                    self._capture_status == CaptureProcessStatus.RECORDING
                    and ctx.can_uncover(p_now, uncov_cfg)
                )
            return False

        return cfg.is_enabled

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
        return self._active_config.pellet_delivery.is_intersession_analysis_enabled and self._session_mouse_seen

    #

    def update_parts_seen(self, pose_rsp: PoseResponse):
        any_ctx = self._parts_pres_ctx_any_cam
        all_ctx = self._parts_pres_ctx_all_cams
        get_seen = all_ctx.get_part_seen
        need_api_post = (
            [SceneElement.R_Hand, ApiEventKind.trialRightHandSeen, get_seen(SceneElement.R_Hand)],
            [SceneElement.Pellet, ApiEventKind.trialPelletSeen, get_seen(SceneElement.Pellet)],
        )
        #
        update_scene_elements_context_from_pose(any_ctx, all_ctx, pose_rsp)
        # little special case for mouse:
        self.update_mouse_seen(pose_rsp.mouse_seen, perf_now=pose_rsp.perf_c)
        #
        post = self._event_manager.post_event_content
        for part, evt, prev_seen in need_api_post:
            if prev_seen != get_seen(part):
                post(evt)

    def update_pellet_seen(self, seen: bool = True):
        self.update_part_seen(SceneElement.Pellet, seen, perf_now=get_perf_now())

    def update_part_seen(self, part, seen: bool, *, perf_now: Optional[float] = None):
        self._parts_pres_ctx_any_cam.update_part_seen(part, seen, perf_now=perf_now)
        self._parts_pres_ctx_all_cams.update_part_seen(part, seen, perf_now=perf_now)

    def pellet_loaded(self):
        self.session_pellet_loaded_count += 1

    def update_triangle_seen(self, seen: bool):
        self.update_part_seen(
            SceneElement.Triangle, seen,
            perf_now=get_perf_now(),
        )

    def update_mouse_seen(self, seen: bool = True, *, perf_now: Optional[float] = None):
        # NB: "mouse" == SceneElement.Nose
        self.update_part_seen(SceneElement.Nose, seen, perf_now=perf_now)  # ensure presence_context gets updated
        if seen:
            if perf_now is None:
                perf_now = get_perf_now()
            self._mouse_seen_last_perf_c = perf_now
        if self._is_in_session and seen:
            prev_seen, self._session_mouse_seen = self._session_mouse_seen, True
            if not prev_seen:
                logger.verbose("Session mouse seen")
                # property currently unused:
                self._on_property_changed(BehaviorAlgoProps.SESSION_MOUSE_SEEN, True, False)
                self._event_manager.post_event_content(ApiEventKind.trialAnimalSeen)

    @property
    def mouse_last_seen_age(self) -> float:
        return get_perf_now() - self._mouse_seen_last_perf_c

    @property
    def session_mouse_seen(self):
        return self._session_mouse_seen

    @property
    def active_config(self) -> BehaviorConfiguration:
        return self._active_config

    @property
    def home_on_excessive_drift_distance_config(self) -> HomeOnExcessiveDriftDistanceConfiguration:
        return self._active_config.home_on_excessive_drift_distance

    @property
    def pellet_delivery_config(self) -> PelletDeliveryConfiguration:
        return self._active_config.pellet_delivery

    #

    def reset_configuration(self):
        """Reset current config to the previous loaded config (via load_configuration)"""
        prev = self._loaded_config
        if prev is not None:
            logger.notice("Resetting config to previous loaded")
            self.load_configuration(prev)

    def load_configuration(self, config: BehaviorConfiguration):
        with self._thread_lock:  # not sure really needed
            # in case of need bigger:
            self._diamond_triangle_prev_drifts = collections.deque(
                # use 50% more, in case of:
                maxlen=int(1.5 * config.home_on_excessive_drift_distance.min_samples))
        self._load_pellet_cfg(config.pellet_delivery)
        if self._topcam_presence is not None:
            self._topcam_presence.load_config(config.topcam_presence_detection)
        self.reload_diamond_triangle_config()
        self._active_config = config  # set it as new active one only at the end,
        #   so that possible on_property_changed event can be relayed if some changed.
        # and/but keep separate copy for eventual reset_config():
        self._loaded_config = copy.deepcopy(config)

    def _load_pellet_cfg(self, cfg: PelletDeliveryConfiguration):
        self.intersession_enabled = cfg.is_intersession_analysis_enabled

    @property
    def diamond_triangle_drift_data_points_size(self) -> int:
        return len(self._diamond_triangle_prev_drifts)

    def get_diamond_triangle_drifts(self, reset: bool = False, show_log: bool = False) -> Optional[Offset3DTuple]:
        """Get the mean of the last seen/saved diamond triangle calculated drifts"""
        with self._thread_lock:
            values = list(self._diamond_triangle_prev_drifts)
            if reset:
                self._diamond_triangle_prev_drifts.clear()
        n_vals = len(values)
        if n_vals < 2:
            new_drift = None if n_vals == 0 else values[-1]
            stdev_drift = Offset3DTuple(0, 0, 0)
        else:
            new_drift, stdev_drift = calculate_std_dev_manual(values)
        #
        prev, self._diamond_triangle_drift = self._diamond_triangle_drift, new_drift
        # self._on_property_changed(BehaviorAlgoProps.PELLET_MOTOR_DRIFT, new_drift, prev)  # property unused atm
        #
        if show_log:
            if n_vals > 4:  # only log if enough data points
                dist = new_drift.distance
                method = logger.error if dist >= 5 else (logger.warning if dist >= 3.5 else logger.verbose)
                method(
                    "motor drift: dist=%.2fmm %s ; min=%s max=%s n_vals=%s stdev=%s",
                    math.nan if new_drift is None else new_drift.distance,
                    None if new_drift is None else new_drift.humanize(n_digits=2),
                    min(values, key=lambda v: v.distance).humanize(n_digits=1),
                    max(values, key=lambda v: v.distance).humanize(n_digits=1),
                    n_vals,
                    stdev_drift.humanize(n_digits=1)
                )
            else:
                logger.verbose("Not enough motor drift measure available")
        return new_drift

    def handle_diamond_triangle_offset(
        self,
        offset: Offset3DTuple,
        motor_position: Offset3DTuple,
    ):
        cfg = self._diamond_triangle_offset_config
        if cfg is None:
            return
        drift = cfg.diamond_to_motor(offset) - motor_position
        with self._thread_lock:
            self._diamond_triangle_prev_drifts.append(drift)
        p_now = time.perf_counter()
        do_report = p_now >= self._diamond_triangle_next_drift_report
        if do_report:
            self.get_diamond_triangle_drifts(show_log=True)
            self._diamond_triangle_next_drift_report = p_now + 2  # log every 2s for now

    def handle_cover_pellet_offset(self, offset: Offset3DTuple):
        self._handle_check_element_distance(self._cover_pellet_distance_ctx, offset)

    def handle_release_pellet_offset(self, offset: Offset3DTuple):
        self._handle_check_element_distance(self._release_pellet_distance_ctx, offset)

    def _handle_check_element_distance(self, ctx: CheckElementDistanceContext, offset: Offset3DTuple):
        if ctx.error_detected:
            # for now: we only set once this flag, never clear it.
            return
        distance = offset.distance
        prev_distance, ctx.distance = ctx.distance, distance
        self._on_property_changed(ctx.distance_property_name, distance, prev_distance)
        is_error = abs(distance - ctx.expected_distance) >= ctx.error_distance_threshold
        if not is_error:
            # we might want to only unset the error_start_perf_c after some minimum duration too
            if ctx.error_start_perf_c is not None:
                ctx.error_start_perf_c = None
                ctx.warned_bad_distance = False
                logger.verbose("End of deviation on %s ; distance=%s",
                            ctx.distance_property_name, distance)
            return
        perf_now = get_perf_now()
        if ctx.error_start_perf_c is None:
            ctx.error_start_perf_c = perf_now
            logger.debug("Detected start of %s deviation ; distance=%.2f expected=%s threshold=%s",
                           ctx.distance_property_name, distance,
                           ctx.expected_distance, ctx.error_distance_threshold)
        else:
            over_duration = perf_now - ctx.error_start_perf_c
            if over_duration >= ctx.error_min_duration_threshold:
                if not ctx.error_detected:
                    logger.critical("Detected %s over threshold ; distance=%.3f prev=%s expected=%s threshold=%s",
                                    ctx.distance_property_name, distance, prev_distance,
                                    ctx.expected_distance, ctx.error_distance_threshold)
                ctx.error_detected = True
                prev_status = self._cover_servo_status
                new_status = CoverServoStatus(prev_status | ctx.cover_servo_status)
                self._cover_servo_status = new_status
                self.cover_servo_status_changed(new_status)  # unused
                self._on_property_changed(BehaviorAlgoProps.COVER_SERVO_STATUS, new_status, prev_status)  # unused
            elif over_duration > ctx.error_min_duration_threshold / 8 and not ctx.warned_bad_distance:
                # this is to not have the warning unnecessarily emitted
                logger.warning("Deviation of %s ongoing ; distance=%.2f expected=%s threshold=%s",
                               ctx.distance_property_name, distance,
                               ctx.expected_distance, ctx.error_distance_threshold)
                ctx.warned_bad_distance = True

    @property
    def trial_reaches(self) -> List[ReachEvent]:
        prev = self._previous_intersession_analysis_rsp
        if prev is None:
            return []
        rsp = prev[1]
        return rsp.reach_events

    def set_previous_intersession_analysis_rsp(self, prj: ProjectInfo, res: IntersessionResponse):
        self._previous_intersession_analysis_rsp = (prj, res)
        self._event_manager.post_event_content(
            ApiEventKind.trialReachEvents, data=dict(trial_reach_events=res.reach_events))

    def reset_selected_animal_counts(self, animal: Optional[AnimalSubject]):
        logger.verbose("Resetting counts for animal change to %s", animal)
        if animal is None:
            self.pellet_shift_y_limit = None
            self.pellets_presented_day = \
            self.pellet_reaches_day = \
            self.pellet_consumed_day = \
            self.successful_reaches_day = 0
            self.pellets_presented_total = \
            self.pellet_reaches_total = \
            self.pellet_consumed_total = \
            self.successful_reaches_total = 0
            return
        self.pellet_shift_y_limit = animal.target_y_limit
        day_counts = animal.pellet_counts_day
        self.pellets_presented_day = day_counts.presented
        self.pellet_consumed_day = day_counts.consumed
        self.pellet_reaches_day = day_counts.reaches
        self.successful_reaches_day = day_counts.success_reaches
        #
        total_counts = animal.pellet_counts_total
        self.pellets_presented_total = total_counts.presented
        self.pellet_consumed_total = total_counts.consumed
        self.pellet_reaches_total = total_counts.reaches
        self.successful_reaches_total = total_counts.success_reaches

    def _start_day(self):
        self.pellet_consumed_day = 0  # consumed
        self.pellets_presented_day = 0
        self.successful_reaches_day = 0
        self.pellet_reaches_day = 0

    # unused atm...
    def _check_date(self):
        today = date.today()
        if today != self._today:
            dt = datetime.combine(today, datetime.min.time())
            self._event_manager.post_event_content(ApiEventKind.dayStarted, dict(date=dt.timestamp()))
            self._today = today
            self._start_day()

    @staticmethod
    def close_algorithm_handler():
        handler_thread, handler_queue = BehaviorAlgorithm._handler_thread_queue  # noqa
        if handler_queue is not None:
            BehaviorAlgorithm._handler_thread_queue = (threading.main_thread(), None)
            if handler_thread.is_alive():
                handler_queue.put(None)
            handler_thread.join(3)
            logger.info("Closed algorithm thread handler")
            if handler_thread.is_alive():
                logger.warning("handler thread still alive")

    # finally:
    relay_func = staticmethod(relay_func)
    # so that it can be used with @BehaviorAlgorithm.relay_func by importers.


import atexit

atexit.register(BehaviorAlgorithm.close_algorithm_handler)
