import logging
import time
from datetime import datetime

from typing_extensions import Self

from autotrainer.core import ObservableObject, EventManager, BehaviorConfiguration, post_trigger_enable

from .behavior_event_kind import BehaviorEventKind
from .system_machine_state import SystemState

logger = logging.getLogger(__name__)


class BehaviorAlgorithm(ObservableObject):
    def __init__(self):
        super().__init__(event_names=("session_starting", "session_ending"))
        self._project_info = None

        self._pellet_delivery_enabled = True
        self._pellet_cover_enabled = True

        self._intersession_enabled = False

        self._head_fixation_enabled = False

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
        self._pellet_delivery_enabled = self._on_property_changed("pellet_delivery_enabled", value,
                                                                  self._pellet_delivery_enabled)

    @property
    def pellet_cover_enabled(self):
        return self._pellet_cover_enabled

    @pellet_cover_enabled.setter
    def pellet_cover_enabled(self, value: bool):
        self._pellet_cover_enabled = self._on_property_changed("pellet_cover_enabled", value,
                                                               self._pellet_cover_enabled)

    @property
    def intersession_enabled(self):
        return self._intersession_enabled

    @intersession_enabled.setter
    def intersession_enabled(self, value: bool):
        self._intersession_enabled = self._on_property_changed("intersession_enabled", value,
                                                               self._intersession_enabled)

    @property
    def head_fixation_enabled(self):
        return self._head_fixation_enabled

    @head_fixation_enabled.setter
    def head_fixation_enabled(self, value: bool):
        old_value = self._head_fixation_enabled

        self._head_fixation_enabled = self._on_property_changed("head_fixation_enabled", value,
                                                                self._head_fixation_enabled)

        if old_value != self._head_fixation_enabled:
            logger.info(f"auto-clamp enabled changed to: {self._head_fixation_enabled}")

    @property
    def baseline_intensity(self):
        return self._baseline_intensity

    @baseline_intensity.setter
    def baseline_intensity(self, value):
        self._baseline_intensity = self._on_property_changed("baseline_intensity", value,
                                                             self._baseline_intensity)
        EventManager.post_event(BehaviorEventKind.headfixBaselineChanged, context=value)

    @property
    def auto_clamp_intensity(self):
        return self._auto_clamp_intensity

    @auto_clamp_intensity.setter
    def auto_clamp_intensity(self, value):
        self._auto_clamp_intensity = self._on_property_changed("auto_clamp_intensity", value,
                                                               self._auto_clamp_intensity)
        EventManager.post_event(BehaviorEventKind.autoClampIntensityChanged, context=value)

    @property
    def auto_clamp_release_tone_freq(self):
        """Frequency of the tone played when auto-clamp is released in Hz"""
        return self._auto_clamp_release_tone_freq

    @auto_clamp_release_tone_freq.setter
    def auto_clamp_release_tone_freq(self, value):
        self._auto_clamp_release_tone_freq = self._on_property_changed("auto_clamp_release_tone_freq", value,
                                                                       self._auto_clamp_release_tone_freq)
        EventManager.post_event(BehaviorEventKind.autoClampReleaseToneFreqChanged, context=value)

    @property
    def auto_clamp_release_delay(self):
        return self._auto_clamp_release_delay

    @auto_clamp_release_delay.setter
    def auto_clamp_release_delay(self, value):
        self._auto_clamp_release_delay = self._on_property_changed("auto_clamp_release_delay", value,
                                                                   self._auto_clamp_release_delay)
        EventManager.post_event(BehaviorEventKind.autoClampReleaseDelayChanged, context=value)

    @property
    def pellet_last_seen(self) -> float:
        return self._pellet_last_seen

    @property
    def day_pellet_count(self):
        return self._day_pellet_count

    @day_pellet_count.setter
    def day_pellet_count(self, value):
        self._day_pellet_count = value

    @property
    def session_pellet_count(self):
        return self._session_pellet_count

    @session_pellet_count.setter
    def session_pellet_count(self, value):
        self._session_pellet_count = value

    @property
    def session_mouse_seen(self):
        return self._session_mouse_seen

    @property
    def pellets_presented(self):
        return self._pellets_presented

    @pellets_presented.setter
    def pellets_presented(self, value):
        self._pellets_presented = value

    @property
    def successful_reaches(self):
        return self._successful_reaches

    @successful_reaches.setter
    def successful_reaches(self, value):
        self._successful_reaches = value

    def start_session(self):
        if self._is_in_session:
            return

        self._session_pellet_count = 0

        EventManager.post_event(BehaviorEventKind.sessionStarting)

        if self._project_info is not None:
            self._project_info.calculate_next_session_index()

        self._is_in_session = True
        self._set_pellet_last_seen(0.0)
        self._session_mouse_seen = False
        self._pellet_seen = False

        post_trigger_enable(self, True)

        self.session_starting()

        EventManager.post_event(BehaviorEventKind.sessionStarted)

    def end_session(self):
        if self._is_in_session:
            EventManager.post_event(BehaviorEventKind.sessionEnding)
            post_trigger_enable(self, False)
            self._is_in_session = False
            self.session_ending()
            EventManager.post_event(BehaviorEventKind.sessionEnded)
            EventManager.flush()

    def reset_session_pellet_count(self):
        self._set_session_pellet_count(0)

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
            EventManager.post_event(BehaviorEventKind.pelletSeen, context=seen)

        if seen:
            self._set_pellet_last_seen(time.time())

    def pellet_loaded(self):
        self._increment_session_pellet_count()

    def mouse_seen(self, seen: bool = True):
        if self._is_in_session and seen:
            was_seen = self._session_mouse_seen
            self._session_mouse_seen = self._on_property_changed("session_mouse_seen", seen, self._session_mouse_seen)
            if not was_seen:
                EventManager.post_event(BehaviorEventKind.sessionMouseSeen)

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

    def _start_day(self):
        self._day_pellet_count = 0

    def _check_date(self):
        today = datetime.now().date()
        if today != self._today:
            EventManager.post_event(BehaviorEventKind.dayStarted)
            self._today = today
            self._start_day()

    def _set_pellet_last_seen(self, value: float):
        self._pellet_last_seen = self._on_property_changed("pellet_last_seen", value, self._pellet_last_seen)

    def _set_session_pellet_count(self, value: int):
        self._session_pellet_count = self._on_property_changed("session_pellet_count", value,
                                                               self._session_pellet_count)

        # if self._session_pellet_count > self.limits.max_pellets_per_session:
        #    self.end_session()

    def _increment_session_pellet_count(self, incr: int = 1):
        value = max(self._session_pellet_count + incr, 0)
        if incr > 0:
            EventManager.post_event(BehaviorEventKind.sessionPelletIncrease, context=value)
        elif incr < 0:
            EventManager.post_event(BehaviorEventKind.sessionPelletDecrease, context=value)
        self._set_session_pellet_count(value)

    def _set_day_pellet_count(self, value: int):
        self._day_pellet_count = self._on_property_changed("day_pellet_count", value,
                                                           self._day_pellet_count)

    def _increment_day_pellet_count(self, incr: int = 1):
        value = max(self._day_pellet_count + incr, 0)
        if incr > 0:
            EventManager.post_event(BehaviorEventKind.dayIncreasePellet, context=value)
        elif incr < 0:
            EventManager.post_event(BehaviorEventKind.dayDecreasePellet, context=value)
        self._set_day_pellet_count(value)
