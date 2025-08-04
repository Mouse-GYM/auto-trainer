import dataclasses
import logging
import math
import threading
import time
from datetime import datetime
from enum import Enum
from typing import Callable, Optional

from typing import Callable
from typing_extensions import Self

from autotrainer.core.logging import get_verbose_logger
from autotrainer.core import ObservableObject, EventManager, BehaviorConfiguration, post_trigger_enable, Offset3DTuple

from .behavior_event_kind import BehaviorEventKind
from .system_machine_state import SystemState


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


class BehaviorProps(str, Enum):
    AUTO_CLAMP_INTENSITY = 'auto_clamp_intensity'
    BASELINE_INTENSITY = 'baseline_intensity'
    DAY_PELLET_COUNT = 'day_pellet_count'
    HEAD_FIXATION_ENABLED = 'head_fixation_enabled'
    INTERSESSION_ENABLED = 'intersession_enabled'
    PELLET_DELIVERY_ENABLED = 'pellet_delivery_enabled'
    PELLET_COVER_ENABLED = 'pellet_cover_enabled'
    SESSION_PELLET_COUNT = 'session_pellet_count'

    PELLET_MOTOR_DRIFT = 'pellet_motor_drift'
    COVER_SERVO_STATUS = 'cover_servo_status'
    COVER_PELLET_DISTANCE = "cover_pellet_distance"
    RELEASE_PELLET_DISTANCE = "release_pellet_distance"


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
        diamond_triangle_known_offset: Optional[Offset3DTuple] = Offset3DTuple(0, 0, 0),  # None,
        cover_error_min_distance_threshold: float = 2,  # math.inf,   # probably millimeter
        release_error_min_distance_threshold: float = 2,  # math.inf,
        cover_release_min_duration_threshold: float = 3,  # seconds
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
        self._head_fixation_enabled = False
        self._clean_raw_data_on_inactive_session = False

        self._auto_clamp_intensity = 100
        self._auto_clamp_release_tone_freq = 7000
        self._auto_clamp_release_delay = 0.1

        self._day_pellet_count = 0

        self._is_in_session = False
        self._session_pellet_count = 0
        self._session_mouse_seen = False
        self._pellet_seen = False

        self._pellet_last_seen = 0.0

        self._system_state = SystemState.cage

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

        self._pellets_presented: int = 0
        self._successful_reaches: int = 0

        self._cover_servo_status = CoverServoStatus.OK

        self._diamond_triangle_known_offset = diamond_triangle_known_offset
        self._diamond_triangle_prev_drift: Optional[Offset3DTuple] = None
        self._diamond_triangle_last_drift_warned = time.time()

        self._cover_pellet_distance_ctx = CheckElementDistanceContext(
            distance_property_name=         BehaviorProps.COVER_PELLET_DISTANCE,
            error_distance_threshold=       cover_error_min_distance_threshold,
            error_min_duration_threshold=   cover_release_min_duration_threshold,
            error_way=                      CheckThresholdWay.TRIGGER_IF_SMALLER,
            cover_servo_status=             CoverServoStatus.COVER_POSITION_ERROR,
        )
        self._release_pellet_distance_ctx = CheckElementDistanceContext(
            distance_property_name=         BehaviorProps.RELEASE_PELLET_DISTANCE,
            error_distance_threshold=       release_error_min_distance_threshold,
            error_min_duration_threshold=   cover_release_min_duration_threshold,
            error_way=                      CheckThresholdWay.TRIGGER_IF_GREATER,
            cover_servo_status=             CoverServoStatus.RELEASE_POSITION_ERROR,
        )

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
    def is_in_session(self) -> bool:
        return self._is_in_session

    @property
    def pellet_delivery_enabled(self):
        return self._pellet_delivery_enabled

    @pellet_delivery_enabled.setter
    def pellet_delivery_enabled(self, value: bool):
        self._pellet_delivery_enabled = self._on_property_changed(BehaviorProps.PELLET_DELIVERY_ENABLED,
                                                                  value, self._pellet_delivery_enabled)

    @property
    def pellet_cover_enabled(self):
        return self._pellet_cover_enabled

    @pellet_cover_enabled.setter
    def pellet_cover_enabled(self, value: bool):
        self._pellet_cover_enabled = self._on_property_changed(BehaviorProps.PELLET_COVER_ENABLED,
                                                               value, self._pellet_cover_enabled)

    @property
    def intersession_enabled(self):
        return self._intersession_enabled

    @intersession_enabled.setter
    def intersession_enabled(self, value: bool):
        self._intersession_enabled = self._on_property_changed(BehaviorProps.INTERSESSION_ENABLED,
                                                               value, self._intersession_enabled)

    @property
    def head_fixation_enabled(self):
        return self._head_fixation_enabled

    @head_fixation_enabled.setter
    def head_fixation_enabled(self, value: bool):
        old_value = self._head_fixation_enabled
        self._head_fixation_enabled = self._on_property_changed(BehaviorProps.HEAD_FIXATION_ENABLED,
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
            self._baseline_intensity = self._on_property_changed(BehaviorProps.BASELINE_INTENSITY,
                                                                 value, self._baseline_intensity)

    @property
    def auto_clamp_intensity(self):
        return self._auto_clamp_intensity

    @auto_clamp_intensity.setter
    def auto_clamp_intensity(self, value):
        self._auto_clamp_intensity = self._on_property_changed(BehaviorProps.AUTO_CLAMP_INTENSITY,
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
    def pellet_last_seen(self) -> float:
        return self._pellet_last_seen

    def _set_pellet_last_seen(self, value: float):
        self._pellet_last_seen = self._on_property_changed("pellet_last_seen", value, self._pellet_last_seen)

    @property
    def day_pellet_count(self):
        return self._day_pellet_count

    @day_pellet_count.setter
    def day_pellet_count(self, value: int):
        prev_value = self._day_pellet_count
        self._day_pellet_count = self._on_property_changed(BehaviorProps.DAY_PELLET_COUNT,
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
        self._session_pellet_count = self._on_property_changed(BehaviorProps.SESSION_PELLET_COUNT,
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
        self._cover_servo_status = self._on_property_changed(BehaviorProps.COVER_SERVO_STATUS,
                                                             status, self._cover_servo_status)
        if status is CoverServoStatus.OK:
            logger.notice("Set cover servo status to %s", status)

    @property
    def diamond_triangle_known_offset(self):
        return self._diamond_triangle_known_offset

    def start_session(self):
        with self._thread_lock:
            if self._is_in_session:
                logger.verbose("start_session() called but already in session")
                return
            self._is_in_session = True

        logger.notice("Starting new session recording ...")
        self._session_pellet_count = 0

        EventManager.default().post_event_content(BehaviorEventKind.sessionStarting)

        if self._project_info is not None:
            self._project_info.calculate_next_session_index()

        self._set_pellet_last_seen(0.0)
        self._session_mouse_seen = False
        self._pellet_seen = False

        post_trigger_enable(self, True)

        self.session_starting()

        EventManager.default().post_event_content(BehaviorEventKind.sessionStarted)

    def end_session(self):
        if self._is_in_session:
            logger.success("Stopping session recording ...")
            EventManager.default().post_event_content(BehaviorEventKind.sessionEnding)
            post_trigger_enable(self, False)
            self._is_in_session = False
            self.session_ending()
            EventManager.default().post_event_content(BehaviorEventKind.sessionEnded)
            EventManager.default().flush()
        else:
            logger.warning("end_session() called but not in session")

    def reset_session_pellet_count(self):
        self.session_pellet_count = 0

    def can_cover_pellet(self):
        return self.pellet_cover_enabled

    def can_load_pellet(self):
        return self.pellet_delivery_enabled and (time.time() - self.pellet_last_seen >= self.limits.pellet_missing_time)

    def can_release_pellet(self) -> bool:
        self._check_date()

        if not self.pellet_cover_enabled:
            if self.system_state.tunnel:
                return self.session_pellet_count <= self.limits.max_pellets_per_session
            else:
                return True

        return self._is_in_session and self.session_pellet_count <= self.limits.max_pellets_per_session

    def can_perform_intersession_analysis(self):
        return self.intersession_enabled and self.session_mouse_seen

    def pellet_seen(self, seen: bool = True):
        if self._pellet_seen != seen:
            self._pellet_seen = seen
            EventManager.default().post_event_content(BehaviorEventKind.pelletSeen, context=seen)

        if seen:
            self._set_pellet_last_seen(time.time())

    def pellet_loaded(self):
        self.session_pellet_count += 1

    def mouse_seen(self, seen: bool = True):
        if self._is_in_session and seen:
            was_seen = self._session_mouse_seen
            self._session_mouse_seen = self._on_property_changed("session_mouse_seen", seen, self._session_mouse_seen)
            if not was_seen:
                EventManager.default().post_event_content(BehaviorEventKind.sessionMouseSeen)

    def load_configuration(self, configuration: BehaviorConfiguration):
        self.pellet_delivery_enabled = configuration.pellet_delivery.is_enabled
        self.pellet_cover_enabled = configuration.pellet_delivery.is_pellet_cover_enabled
        self.pellet_missing_time = configuration.pellet_delivery.max_pellet_missing_seconds
        self.max_pellets_per_session = configuration.pellet_delivery.max_pellets_per_session
        self.max_pellets_per_day = configuration.pellet_delivery.max_pellets_per_day

        self.min_baseline_intensity = configuration.head_clamp.min_baseline_intensity
        self.max_baseline_intensity = configuration.head_clamp.max_baseline_intensity
        self.baseline_intensity_increment = configuration.head_clamp.baseline_intensity_increment

        self.auto_clamp_intensity = configuration.head_clamp.auto_clamp_intensity
        self.auto_clamp_release_tone_freq = configuration.head_clamp.auto_clamp_release_tone_freq
        self.auto_clamp_release_delay = configuration.head_clamp.auto_clamp_release_tone_delay

    def update_configuration(self, configuration: BehaviorConfiguration):
        configuration.pellet_delivery.is_enabled = self.pellet_delivery_enabled
        configuration.pellet_delivery.is_pellet_cover_enabled = self.pellet_cover_enabled
        configuration.pellet_delivery.max_pellet_missing_seconds = self.pellet_missing_time
        configuration.pellet_delivery.max_pellets_per_session = self.max_pellets_per_session
        configuration.pellet_delivery.max_pellets_per_day = self.max_pellets_per_day

        configuration.head_clamp.min_baseline_intensity = self.min_baseline_intensity
        configuration.head_clamp.max_baseline_intensity = self.max_baseline_intensity
        configuration.head_clamp.baseline_intensity_increment = self.baseline_intensity_increment

        configuration.head_clamp.auto_clamp_intensity = self.auto_clamp_intensity
        configuration.head_clamp.auto_clamp_release_tone_freq = self.auto_clamp_release_tone_freq
        configuration.head_clamp.auto_clamp_release_tone_delay = self.auto_clamp_release_delay

    def handle_diamond_triangle_offset(self, offset: Offset3DTuple):
        known_offset = self._diamond_triangle_known_offset
        if known_offset is None:
            return
        prev = self._diamond_triangle_prev_drift
        drift = known_offset - offset
        if __debug__:
            d_drift = None if prev is None else prev - drift
            # not sure which abs_diff to check against:
            if d_drift is not None and any(abs(d) > 2.5 for d in d_drift):
                t_now = time.time()
                if t_now > self._diamond_triangle_last_drift_warned + 1:  # max 1 / s
                    logger.verbose("diamond triangle offset drift: %s d_drift=%s", drift, d_drift)
                    self._diamond_triangle_last_drift_warned = t_now
        if prev != drift:
            self.pellet_motor_drift_changed(drift)
        self._diamond_triangle_prev_drift = self._on_property_changed(BehaviorProps.PELLET_MOTOR_DRIFT, drift, prev)

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
                    BehaviorProps.COVER_SERVO_STATUS, new_status, prev_status)

    def _start_day(self):
        self._day_pellet_count = 0

    def _check_date(self):
        today = datetime.now().date()
        if today != self._today:
            EventManager.default().post_event_content(BehaviorEventKind.dayStarted)
            self._today = today
            self._start_day()
