from dataclasses import dataclass

from autotrainer.core import ObservableObject


@dataclass(frozen=True)
class BehaviorModelLimits:
    min_baseline_intensity: int = 10
    max_baseline_intensity: int = 90
    max_pellets_per_session: int = 10
    max_pellets_per_day: int = 50
    pellet_missing_time: float = 15.0


class BehaviorModelProperties(ObservableObject):
    def __init__(self, limits: BehaviorModelLimits):
        super().__init__()

        self._limits = limits

        self._pellet_delivery_enabled = True
        self._head_fixation_enabled = True
        self._reach_detection_enabled = True

        self._baseline_intensity = limits.min_baseline_intensity
        self._current_session_pellets = 0
        self._current_day_pellets = 0

        self._pellet_missing = False

    @property
    def limits(self) -> BehaviorModelLimits:
        return self._limits

    @limits.setter
    def limits(self, limits: BehaviorModelLimits):
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
    def pellet_missing(self):
        return self._pellet_missing

    @pellet_missing.setter
    def pellet_missing(self, value: bool):
        self._pellet_missing = self._on_property_changed("pellet_missing", value, self._pellet_missing)
