from dataclasses import dataclass


@dataclass(frozen=True)
class BehaviorLimits:
    min_baseline_intensity: float = 5.0
    max_baseline_intensity: float = 90.0
    baseline_intensity_increment: float = 15.0
    max_pellets_per_session: int = 10
    max_pellets_per_headfix_session: int = 10
    max_pellets_per_day: int = 50
    pellet_missing_time: float = 1.0

    @staticmethod
    def from_dictionary(values: dict):
        kwargs = dict()

        if "maxPelletMissingSeconds" in values:
            kwargs["pellet_missing_time"] = values["maxPelletMissingSeconds"]

        if "maxPelletsPerSession" in values:
            kwargs["max_pellets_per_session"] = values["maxPelletsPerSession"]
        if "maxPelletsPerDay" in values:
            kwargs["max_pellets_per_day"] = values["maxPelletsPerDay"]

        return BehaviorLimits(**kwargs)
