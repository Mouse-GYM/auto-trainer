import time
from datetime import datetime

from autotrainer.core import ObservableObject

from .behavior_limits import BehaviorLimits


class BehaviorAlgorithm(ObservableObject):
    def __init__(self, limits: BehaviorLimits):
        super().__init__()

        self._limits = limits

        self._pellet_delivery_enabled = True
        self._head_fixation_enabled = True
        self._reach_detection_enabled = True

        self._baseline_intensity = limits.min_baseline_intensity
        self._session_pellet_count = 0
        self._day_pellet_count = 0

        self._session_mouse_seen = False

        self._pellet_last_seen = 0.0

        self._today = None

        self._start_day()

    @property
    def pellet_delivery_enabled(self):
        return self._pellet_delivery_enabled

    @pellet_delivery_enabled.setter
    def pellet_delivery_enabled(self, value: bool):
        self._pellet_delivery_enabled = value

    @property
    def limits(self) -> BehaviorLimits:
        return self._limits

    @limits.setter
    def limits(self, limits: BehaviorLimits):
        self._limits = limits

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
        self._set_session_pellet_count(0)
        self._set_pellet_last_seen(0.0)
        self._session_mouse_seen = False

    def can_release_pellet(self) -> bool:
        self._check_date()

        if time.time() - self.pellet_last_seen >= self.limits.pellet_missing_time:
            if self.session_pellet_count < self.limits.max_pellets_per_session and self._day_pellet_count < self.limits.max_pellets_per_day:
                return True

        return False

    def pellet_seen(self, seen: bool = True):
        if seen:
            self._set_pellet_last_seen(time.time())

    def pellet_released(self):
        self._increment_session_pellet_count()
        self._day_pellet_count += 1

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

    def _increment_session_pellet_count(self, incr: int = 1):
        value = self._session_pellet_count + incr
        self._session_pellet_count = self._on_property_changed("session_pellet_count", value,
                                                               self._session_pellet_count)
