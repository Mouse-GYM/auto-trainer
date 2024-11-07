import time
from datetime import datetime

from autotrainer.core import ObservableObject

from .behavior_limits import BehaviorLimits


class BehaviorAlgorithm(ObservableObject):
    def __init__(self, limits: BehaviorLimits = None):
        super().__init__(event_names=("session_starting", "session_ending"))

        self._limits = limits or BehaviorLimits()

        self._project_info = None

        self._pellet_delivery_enabled = True
        self._pellet_cover_enabled = True

        self._intersession_enabled = False

        self._baseline_intensity = limits.min_baseline_intensity
        self._day_pellet_count = 0

        self._is_in_session = False
        self._session_pellet_count = 0
        self._session_mouse_seen = False

        self._pellet_last_seen = 0.0

        self._today = None

        self._start_day()

    @property
    def limits(self) -> BehaviorLimits:
        return self._limits

    @limits.setter
    def limits(self, limits: BehaviorLimits):
        self._limits = limits

    @property
    def project(self):
        return self._project_info

    @project.setter
    def project(self, project):
        self._project_info = project

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
    def baseline_intensity(self):
        return self._baseline_intensity

    @property
    def pellet_last_seen(self) -> float:
        return self._pellet_last_seen

    @property
    def day_pellet_count(self):
        return self._day_pellet_count

    @property
    def session_pellet_count(self):
        return self._session_pellet_count

    @property
    def session_mouse_seen(self):
        return self._session_mouse_seen

    def start_session(self):
        self.end_session()

        self._set_session_pellet_count(0)
        self._set_pellet_last_seen(0.0)
        self._is_in_session = True
        self._session_mouse_seen = False

        self.session_starting()

    def end_session(self):
        if self._is_in_session:
            self._is_in_session = False
            self.session_ending()

    def can_cover_pellet(self):
        return self.pellet_cover_enabled

    def can_load_pellet(self):
        return self.pellet_delivery_enabled and (time.time() - self.pellet_last_seen >= self.limits.pellet_missing_time)

    def can_release_pellet(self) -> bool:
        self._check_date()

        return (self._is_in_session or not self.pellet_cover_enabled) and self.session_pellet_count < self.limits.max_pellets_per_session and \
            self._day_pellet_count < self.limits.max_pellets_per_day

    def can_perform_intersession_analysis(self):
        return self.intersession_enabled and self.session_mouse_seen

    def pellet_seen(self, seen: bool = True):
        if seen:
            self._set_pellet_last_seen(time.time())

    def pellet_covered(self):
        self._increment_session_pellet_count(-1)
        self._increment_day_pellet_count(-1)

    def pellet_released(self):
        self._increment_session_pellet_count()
        self._increment_day_pellet_count()

    def mouse_seen(self, seen: bool = True):
        if seen:
            self._session_mouse_seen = self._on_property_changed("session_mouse_seen", seen, self._session_mouse_seen)

    def _start_day(self):
        self._day_pellet_count = 0

    def _check_date(self):
        today = datetime.now().date()
        if today != self._today:
            self._today = today
            self._start_day()

    def _set_pellet_last_seen(self, value: float):
        self._pellet_last_seen = self._on_property_changed("pellet_last_seen", value, self._pellet_last_seen)

    def _set_session_pellet_count(self, value: int):
        self._session_pellet_count = self._on_property_changed("session_pellet_count", value,
                                                               self._session_pellet_count)

        if self._session_pellet_count == self.limits.max_pellets_per_session:
            self.end_session()

    def _increment_session_pellet_count(self, incr: int = 1):
        value = max(self._session_pellet_count + incr, 0)
        self._set_session_pellet_count(value)

    def _set_day_pellet_count(self, value: int):
        self._day_pellet_count = self._on_property_changed("day_pellet_count", value,
                                                           self._day_pellet_count)

    def _increment_day_pellet_count(self, incr: int = 1):
        value = max(self._day_pellet_count + incr, 0)
        self._set_day_pellet_count(value)
