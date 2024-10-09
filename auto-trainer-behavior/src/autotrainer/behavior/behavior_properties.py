from autotrainer.core import ObservableObject

from .behavior_limits import BehaviorLimits


class BehaviorProperties(ObservableObject):
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

        self._pellet_missing_time = 0.0

    @property
    def limits(self) -> BehaviorLimits:
        return self._limits

    @limits.setter
    def limits(self, limits: BehaviorLimits):
        self._limits = limits

    @property
    def baseline_intensity(self):
        return self._baseline_intensity

    @baseline_intensity.setter
    def baseline_intensity(self, value: int):
        self._baseline_intensity = self._on_property_changed("baseline_intensity", value, self._baseline_intensity)

    @property
    def pellet_delivery_enabled(self):
        return self._pellet_delivery_enabled

    @pellet_delivery_enabled.setter
    def pellet_delivery_enabled(self, value: bool):
        self._pellet_delivery_enabled = value

    @property
    def pellet_missing_time(self):
        return self._pellet_missing_time

    @pellet_missing_time.setter
    def pellet_missing_time(self, value: bool):
        self._pellet_missing_time = self._on_property_changed("pellet_missing_time", value, self._pellet_missing_time)

    @property
    def session_pellet_count(self):
        return self._session_pellet_count

    @session_pellet_count.setter
    def session_pellet_count(self, value: int):
        self._session_pellet_count = self._on_property_changed("session_pellet_count", value,
                                                               self._session_pellet_count)

    @property
    def session_mouse_seen(self):
        return self._session_mouse_seen

    @session_mouse_seen.setter
    def session_mouse_seen(self, value: bool):
        self._session_mouse_seen = self._on_property_changed("session_mouse_seen", value, self._session_mouse_seen)

    def start_session(self):
        self.session_pellet_count = 0
        self.pellet_missing_time = 0.0
        self.session_mouse_seen = False
