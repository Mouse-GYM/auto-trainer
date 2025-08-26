import dataclasses
import logging
import math
import operator
import statistics
import threading
import time
from datetime import datetime
from enum import Enum
from functools import reduce
from pathlib import Path
from typing import Callable, Optional, Tuple, List

from typing import Callable

import yaml
from typing_extensions import Self

from autotrainer.core.logging import get_verbose_logger
from autotrainer.core import ObservableObject, EventManager, BehaviorConfiguration, post_trigger_enable, Offset3DTuple
from . import DiamondTriangleOffsetConfig

from .behavior_event_kind import BehaviorEventKind
from .system_machine_state import SystemState
from .intersession import IntersessionState
from autotrainer.core.configuration.behavior_configuration import PelletDeliveryConfiguration
from autotrainer.video import CaptureProcessStatus

logger = get_verbose_logger(__name__)


class CheckThresholdWay(str, Enum):
    TRIGGER_IF_GREATER = "trigger_if_greater"
    TRIGGER_IF_SMALLER = "trigger_if_smaller"


class CoverServoStatus(int, Enum):
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


class BehaviorAlgoProps(str, Enum):
    AUTO_CLAMP_INTENSITY = 'auto_clamp_intensity'
    BASELINE_INTENSITY = 'baseline_intensity'
    DAY_PELLET_COUNT = 'day_pellet_count'
    HEAD_FIXATION_ENABLED = 'head_fixation_enabled'
    INTERSESSION_ENABLED = 'intersession_enabled'
    INTERSESSION_PELLET_SHIFT_ENABLED = 'intersession_pellet_shift_enabled'
    PELLET_DELIVERY_ENABLED = 'pellet_delivery_enabled'
    PELLET_COVER_ENABLED = 'pellet_cover_enabled'
    SESSION_PELLET_COUNT = 'session_pellet_count'

    AUTO_CORRECT_MOTOR_DRIFT = 'auto_correct_motor_drift'
    PELLET_MOTOR_DRIFT = 'pellet_motor_drift'
    COVER_SERVO_STATUS = 'cover_servo_status'
    COVER_PELLET_DISTANCE = "cover_pellet_distance"
    RELEASE_PELLET_DISTANCE = "release_pellet_distance"

    INTERSESSION_STATE = 'intersession_state'
    CAPTURE_STATUS = 'capture_status'

    USE_TRIANGLE_PELLET_DISTANCE_TOO_FAR = "use_triangle_pellet_distance_too_far"
    TRIANGLE_PELLET_DISTANCE = "triangle_pellet_distance"


class BehaviorAlgorithm(ObservableObject):
    # dynamic events type hints,
    # helps IDE search/completion/type-verification:
    session_starting: Callable[[], None]
    session_ending: Callable[[], None]

    pellet_motor_drift_changed: Callable[[Offset3DTuple], None]
    cover_servo_status_changed: Callable[[CoverServoStatus], None]

    def __init__(
            self,
            *,
            cover_error_min_distance_threshold: float = 2,  # math.inf,   # probably millimeter
            release_error_min_distance_threshold: float = 2,  # math.inf,
            cover_release_min_duration_threshold: float = 3,  # seconds
            diamond_triangle_offset_config_path: Optional[Path] = DiamondTriangleOffsetConfig.DEFAULT_CONFIG_PATH,
    ):
        super().__init__(event_names=(
            "session_starting",
            "session_ending",
            "cover_servo_status_changed",
            "pellet_motor_drift_changed",
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
        self._auto_clamp_release_delay = 0.1

        self._recording_age_release_pellet_threshold = 0.75

        self._day_pellet_count = 0

        self._is_in_session = False
        self._session_start_perf_c = time.perf_counter()
        self._start_session_reason = "NA"
        self._stop_session_perf_c = time.perf_counter()
        self._stop_session_reason = "NA"

        self._session_pellet_count = 0
        self._session_mouse_seen = False
        self._pellet_seen = False
        self._triangle_seen = False

        self._pellet_last_seen = 0.0
        self._triangle_last_seen = 0.0
        self._triangle_pellet_last_offset = Offset3DTuple(math.nan, math.nan, math.nan)
        self._use_triangle_pellet_distance_too_far = False
        self._triangle_pellet_diff_too_far_threshold: float = PelletDeliveryConfiguration.triangle_pellet_diff_too_far_threshold
        self._triangle_pellet_expected_distance = PelletDeliveryConfiguration.triangle_pellet_expected_distance

        self._system_state = SystemState.cage
        self._intersession_state = IntersessionState.idle
        self._capture_status = CaptureProcessStatus.UNKNOWN
        self._last_capture_status_change_perf_c = time.perf_counter()

        self._today = None

        self._start_day()

        self.min_baseline_intensity: float = 5.0
        self.max_baseline_intensity: float = 90.0
        self._baseline_intensity = self.min_baseline_intensity
        self.baseline_intensity_increment: float = 15.0
        self.max_pellets_per_session: int = 10
        self.max_pellets_per_headfix_session: int = 10
        self.max_pellets_per_day: int = 50
        self.pellet_missing_time: float = 1.0
        self.triangle_missing_time: float = 1.0

        self._pellets_presented: int = 0
        self._successful_reaches: int = 0

        self._cover_servo_status = CoverServoStatus.OK

        self._diamond_triangle_offest_config_path = diamond_triangle_offset_config_path
        self._load_diamond_config()

        self._diamond_triangle_drift: Optional[Offset3DTuple] = None
        self._diamond_triangle_prev_drifts: List[Offset3DTuple] = []
        self._diamond_triangle_last_drift_warned = time.perf_counter()

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
        self._intersession_state = self._on_property_changed(BehaviorAlgoProps.INTERSESSION_STATE, value, self._intersession_state)

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
    def recording_age_release_pellet_threshold(self):
        return self._recording_age_release_pellet_threshold

    @property
    def is_in_session(self) -> bool:
        return self._is_in_session

    @property
    def pellet_delivery_enabled(self):
        return self._pellet_delivery_enabled

    @pellet_delivery_enabled.setter
    def pellet_delivery_enabled(self, value: bool):
        self._pellet_delivery_enabled = self._on_property_changed(BehaviorAlgoProps.PELLET_DELIVERY_ENABLED,
                                                                  value, self._pellet_delivery_enabled)

    @property
    def pellet_cover_enabled(self):
        return self._pellet_cover_enabled

    @pellet_cover_enabled.setter
    def pellet_cover_enabled(self, value: bool):
        self._pellet_cover_enabled = self._on_property_changed(BehaviorAlgoProps.PELLET_COVER_ENABLED,
                                                               value, self._pellet_cover_enabled)

    @property
    def intersession_enabled(self):
        return self._intersession_enabled

    @intersession_enabled.setter
    def intersession_enabled(self, value: bool):
        self._intersession_enabled = self._on_property_changed(BehaviorAlgoProps.INTERSESSION_ENABLED,
                                                               value, self._intersession_enabled)

    @property
    def intersession_pellet_shift_enabled(self):
        return self._intersession_pellet_shift_enabled

    @intersession_pellet_shift_enabled.setter
    def intersession_pellet_shift_enabled(self, value: bool):
        self._intersession_pellet_shift_enabled = self._on_property_changed(
            BehaviorAlgoProps.INTERSESSION_PELLET_SHIFT_ENABLED,
            value,
            self._intersession_pellet_shift_enabled)

    @property
    def head_fixation_enabled(self):
        return self._head_fixation_enabled

    @head_fixation_enabled.setter
    def head_fixation_enabled(self, value: bool):
        old_value = self._head_fixation_enabled
        self._head_fixation_enabled = self._on_property_changed(BehaviorAlgoProps.HEAD_FIXATION_ENABLED,
                                                                value, self._head_fixation_enabled)
        if old_value != self._head_fixation_enabled:
            logger.info(f"auto-clamp enabled changed to: {self._head_fixation_enabled}")

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
        if value != self._baseline_intensity:
            EventManager.default().post_event_content(BehaviorEventKind.headfixBaselineChanged, context=value)
            self._baseline_intensity = self._on_property_changed(BehaviorAlgoProps.BASELINE_INTENSITY,
                                                                 value, self._baseline_intensity)

    @property
    def auto_clamp_intensity(self):
        return self._auto_clamp_intensity

    @auto_clamp_intensity.setter
    def auto_clamp_intensity(self, value):
        self._auto_clamp_intensity = self._on_property_changed(BehaviorAlgoProps.AUTO_CLAMP_INTENSITY,
                                                               value, self._auto_clamp_intensity)
        EventManager.default().post_event_content(BehaviorEventKind.autoClampIntensityChanged, context=value)

    @property
    def auto_clamp_release_tone_freq(self):
        """Frequency of the tone played when auto-clamp is released in Hz"""
        return self._auto_clamp_release_tone_freq

    @auto_clamp_release_tone_freq.setter
    def auto_clamp_release_tone_freq(self, value):
        self._auto_clamp_release_tone_freq = self._on_property_changed("auto_clamp_release_tone_freq", value,
                                                                       self._auto_clamp_release_tone_freq)
        EventManager.default().post_event_content(BehaviorEventKind.autoClampReleaseToneFreqChanged, context=value)

    @property
    def auto_clamp_release_delay(self):
        return self._auto_clamp_release_delay

    @auto_clamp_release_delay.setter
    def auto_clamp_release_delay(self, value):
        self._auto_clamp_release_delay = self._on_property_changed("auto_clamp_release_delay", value,
                                                                   self._auto_clamp_release_delay)
        EventManager.default().post_event_content(BehaviorEventKind.autoClampReleaseDelayChanged, context=value)

    @property
    def triangle_last_seen(self) -> float:
        return self._triangle_last_seen

    @property
    def triangle_recently_seen(self) -> bool:
        return time.perf_counter() - self._triangle_last_seen < self.limits.triangle_missing_time

    @property
    def pellet_last_seen(self) -> float:
        return self._pellet_last_seen

    @property
    def triangle_pellet_offset(self) -> Offset3DTuple:
        return self._triangle_pellet_last_offset

    @triangle_pellet_offset.setter
    def triangle_pellet_offset(self, value):
        prev, self._triangle_pellet_last_offset = self._triangle_pellet_last_offset, value
        self._on_property_changed(BehaviorAlgoProps.TRIANGLE_PELLET_DISTANCE, self.triangle_pellet_distance, prev.distance)

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
    def day_pellet_count(self):
        return self._day_pellet_count

    @day_pellet_count.setter
    def day_pellet_count(self, value: int):
        prev_value = self._day_pellet_count
        self._day_pellet_count = self._on_property_changed(BehaviorAlgoProps.DAY_PELLET_COUNT,
                                                           value, self._day_pellet_count)
        incr = value - prev_value
        if incr > 0:
            EventManager.default().post_event_content(BehaviorEventKind.dayIncreasePellet, context=value)
        elif incr < 0:
            EventManager.default().post_event_content(BehaviorEventKind.dayDecreasePellet, context=value)

    @property
    def session_pellet_count(self):
        return self._session_pellet_count

    @session_pellet_count.setter
    def session_pellet_count(self, value):
        prev = self._session_pellet_count
        self._session_pellet_count = self._on_property_changed(BehaviorAlgoProps.SESSION_PELLET_COUNT,
                                                               value, self._session_pellet_count)
        incr = value - prev
        if incr > 0:
            EventManager.default().post_event_content(BehaviorEventKind.sessionPelletIncrease, context=value)
        elif incr < 0:
            EventManager.default().post_event_content(BehaviorEventKind.sessionPelletDecrease, context=value)
        # if self._session_pellet_count > self.limits.max_pellets_per_session:
        #    self.end_session()

    @property
    def session_mouse_seen(self):
        return self._session_mouse_seen

    @property
    def pellets_presented(self):
        return self._pellets_presented

    @pellets_presented.setter
    def pellets_presented(self, value):
        prev = self._pellets_presented
        self._pellets_presented = self._on_property_changed("pellets_presented", value, prev)
        if prev != value:
            EventManager.default().post_event_content(BehaviorEventKind.pelletPresented, context=value)

    @property
    def successful_reaches(self):
        return self._successful_reaches

    @successful_reaches.setter
    def successful_reaches(self, value):
        prev = self._successful_reaches
        self._successful_reaches = self._on_property_changed("successful_reaches", value, prev)
        if prev != value:
            EventManager.default().post_event_content(BehaviorEventKind.pelletSuccessfulReach, context=value)

    @property
    def cover_servo_status(self) -> CoverServoStatus:
        return self._cover_servo_status

    @cover_servo_status.setter
    def cover_servo_status(self, status: CoverServoStatus):
        self._cover_servo_status = self._on_property_changed(BehaviorAlgoProps.COVER_SERVO_STATUS,
                                                             status, self._cover_servo_status)
        if status is CoverServoStatus.OK:
            logger.notice("Set cover servo status to %s", status)

    @property
    def diamond_triangle_drift(self) -> Optional[Offset3DTuple]:
        return self._diamond_triangle_drift

    @property
    def auto_correct_motors_drift(self) -> bool:
        return self._auto_correct_motors_drift

    @auto_correct_motors_drift.setter
    def auto_correct_motors_drift(self, value):
        prev, self._auto_correct_motors_drift = self._auto_correct_motors_drift, value
        self._on_property_changed(BehaviorAlgoProps.AUTO_CORRECT_MOTOR_DRIFT, value, prev)

    def _load_diamond_config(self):
        cfg_path = self._diamond_triangle_offest_config_path
        if cfg_path is None:
            logger.notice("No diamond-triangle offset config path provided")
        else:
            if not cfg_path.expanduser().is_file():
                logger.warning("Diamond triangle config %r not a file", cfg_path.as_posix())
            else:
                self._diamond_triangle_offset_config = DiamondTriangleOffsetConfig.from_file(
                    cfg_path
                )

    def start_session(self, *, reason: str="NA"):
        with self._thread_lock:
            self._start_session(reason=reason)

    def _start_session(self, *, reason: str):
        if self._is_in_session:
            logger.warning("%s: start_session() called but already in session",
                           reason)
            return

        logger.success("%s: starting new session recording ...", reason)
        EventManager.default().post_event_content(BehaviorEventKind.sessionStarting)
        self._is_in_session = True
        self._start_session_reason = reason
        self._session_pellet_count = 0
        self._session_start_perf_c = time.perf_counter()

        if self._project_info is not None:
            self._project_info.calculate_next_session_index()

        self._set_pellet_last_seen(0.0)
        self._set_triangle_last_seen(0.0)
        self._session_mouse_seen = False
        self._pellet_seen = False

        # this is what send the trigger the enable recording at camera level,
        # but must be done after calculate next session index !!
        post_trigger_enable(self, True)

        self._load_diamond_config()

        self.session_starting()

        EventManager.default().post_event_content(BehaviorEventKind.sessionStarted)

    def end_session(self, *, reason: str="NA"):
        with self._thread_lock:
            self._end_session(reason=reason)

    def _end_session(self, *, reason: str):
        if not self._is_in_session:
            logger.warning("%s: end_session() called but not in session (out reason: %s)",
                           reason, self._stop_session_reason)
            return
        logger.success("%s: stopping session recording", reason)
        self._is_in_session = False  # must be ~first, to ensure next actions/callbacks don't see it as True
        # but must be at least before self.session_ending() here after, given test_covered_load_cycle rely on that atm.
        self._stop_session_reason = reason
        self._stop_session_perf_c = time.perf_counter()
        EventManager.default().post_event_content(BehaviorEventKind.sessionEnding)
        post_trigger_enable(self, False)  # tells cameras processes to stop recording - ASYNC
        self.session_ending()
        EventManager.default().post_event_content(BehaviorEventKind.sessionEnded)
        EventManager.default().flush()

    def reset_session_pellet_count(self):
        self.session_pellet_count = 0

    def can_cover_pellet(self):
        return self.pellet_cover_enabled

    def can_load_pellet(self):
        return (
            self.pellet_delivery_enabled
            and time.perf_counter() - self._pellet_last_seen >= self.limits.pellet_missing_time
        )

    def can_release_pellet(self) -> bool:
        # self._check_date()

        if self.pellet_cover_enabled:
            if self._is_in_session:
                if self._stop_session_perf_c < self._session_start_perf_c:
                    recording_aged_enough = (
                        self._capture_status == CaptureProcessStatus.RECORDING
                        and self.capture_status_age >= self._recording_age_release_pellet_threshold
                    )
                    if not recording_aged_enough:
                        return False
            return self._is_in_session

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
        return self.intersession_enabled and self.session_mouse_seen

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
            was_seen = self._session_mouse_seen
            self._session_mouse_seen = self._on_property_changed("session_mouse_seen", seen, self._session_mouse_seen)
            if not was_seen:
                EventManager.default().post_event_content(BehaviorEventKind.sessionMouseSeen)

    def load_configuration(self, configuration: BehaviorConfiguration):
        pellet_deliver_cfg = configuration.pellet_delivery
        self.pellet_delivery_enabled = pellet_deliver_cfg.is_enabled
        self.pellet_cover_enabled = pellet_deliver_cfg.is_pellet_cover_enabled
        self.pellet_missing_time = pellet_deliver_cfg.max_pellet_missing_seconds
        self.max_pellets_per_session = pellet_deliver_cfg.max_pellets_per_session
        self.max_pellets_per_day = pellet_deliver_cfg.max_pellets_per_day
        self.intersession_pellet_shift_enabled = pellet_deliver_cfg.is_intersession_pellet_shift_enabled
        self.use_triangle_pellet_distance_too_far = pellet_deliver_cfg.use_triangle_pellet_distance_too_far
        self.triangle_pellet_diff_too_far_threshold = pellet_deliver_cfg.triangle_pellet_diff_too_far_threshold

        self.auto_correct_motors_drift = configuration.pellet_delivery.auto_correct_motors_drift

        self.min_baseline_intensity = configuration.head_clamp.min_baseline_intensity
        self.max_baseline_intensity = configuration.head_clamp.max_baseline_intensity
        self.baseline_intensity_increment = configuration.head_clamp.baseline_intensity_increment

        self.auto_clamp_intensity = configuration.head_clamp.auto_clamp_intensity
        self.auto_clamp_release_tone_freq = configuration.head_clamp.auto_clamp_release_tone_freq
        self.auto_clamp_release_delay = configuration.head_clamp.auto_clamp_release_tone_delay

    def update_configuration(self, configuration: BehaviorConfiguration):
        pellet_cfg = configuration.pellet_delivery
        pellet_cfg.is_enabled = self.pellet_delivery_enabled
        pellet_cfg.is_pellet_cover_enabled = self.pellet_cover_enabled
        pellet_cfg.max_pellet_missing_seconds = self.pellet_missing_time
        pellet_cfg.max_pellets_per_session = self.max_pellets_per_session
        pellet_cfg.max_pellets_per_day = self.max_pellets_per_day
        pellet_cfg.auto_correct_motors_drift = self._auto_correct_motors_drift
        pellet_cfg.use_triangle_pellet_distance_too_far = self.use_triangle_pellet_distance_too_far
        pellet_cfg.triangle_pellet_expected_distance = self.triangle_pellet_expected_distance
        pellet_cfg.triangle_pellet_diff_too_far_threshold = self.triangle_pellet_diff_too_far_threshold

        configuration.head_clamp.min_baseline_intensity = self.min_baseline_intensity
        configuration.head_clamp.max_baseline_intensity = self.max_baseline_intensity
        configuration.head_clamp.baseline_intensity_increment = self.baseline_intensity_increment

        configuration.head_clamp.auto_clamp_intensity = self.auto_clamp_intensity
        configuration.head_clamp.auto_clamp_release_tone_freq = self.auto_clamp_release_tone_freq
        configuration.head_clamp.auto_clamp_release_tone_delay = self.auto_clamp_release_delay

    def get_diamond_triangle_drifts(self, reset: bool=False) -> Offset3DTuple:
        values = self._diamond_triangle_prev_drifts
        tot = reduce(operator.add, values, Offset3DTuple(0, 0, 0))
        n_vals = len(values)
        if reset:
            self._diamond_triangle_prev_drifts = []
        new_drift = Offset3DTuple(0, 0, 0) if n_vals == 0 else tot / n_vals
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Motor mean drift: %s\nall motors drifts: %s",
                         new_drift.humanize(n_digits=3), [v.humanize(n_digits=1) for v in values])
        # put here to minimize nbr of times we update it:
        prev, self._diamond_triangle_drift = self._diamond_triangle_drift, new_drift
        self._on_property_changed(BehaviorAlgoProps.PELLET_MOTOR_DRIFT, new_drift, prev)
        return new_drift

    def handle_diamond_triangle_offset(
        self,
        offset: Offset3DTuple,
        position: Offset3DTuple,
        *,
        flips: Offset3DTuple = Offset3DTuple(1, 1, 1),
    ):
        cfg = self._diamond_triangle_offset_config
        if cfg is None:
            return
        prev = self._diamond_triangle_drift
        drift = flips * (cfg.measured_offset - offset) - (cfg.used_position - position)
        if prev is None:
            prev = Offset3DTuple(0, 0, 0)
        logger.spam("Measured motor drift: %s (prev=%s) ; pos=%s offset=%s",
                       drift.humanize(), prev.humanize(), position.humanize(), offset.humanize())
        if __debug__:
            d_drift = drift if prev is None else prev + drift
            # not sure which abs_diff to check against:
            if d_drift is not None and any(abs(d) > 2.5 for d in d_drift):
                perf_now = time.perf_counter()
                if perf_now > self._diamond_triangle_last_drift_warned + 1:  # max 1 / s
                    logger.verbose("diamond triangle offset drift: %s d_drift=%s", drift, d_drift)
                    self._diamond_triangle_last_drift_warned = perf_now
        self._diamond_triangle_drift = drift
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

    def _start_day(self):
        self._day_pellet_count = 0

    def _check_date(self):
        today = datetime.now().date()
        if today != self._today:
            EventManager.default().post_event_content(BehaviorEventKind.dayStarted)
            self._today = today
            self._start_day()
