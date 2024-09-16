from dataclasses import dataclass

from autotrainer.core import ObservableObject


@dataclass(frozen=True)
class BehaviorModelLimits:
    min_baseline_intensity: int = 10
    max_baseline_intensity: int = 90
    max_pellets_per_session: int = 10
    max_pellets_per_day: int = 50


class BehaviorModelProperties(ObservableObject):
    def __init__(self, limits: BehaviorModelLimits):
        super().__init__()

        self._limits = limits

        self._baseline_intensity = limits.min_baseline_intensity
        self._current_session_pellets = 0
        self._current_day_pellets = 0

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
