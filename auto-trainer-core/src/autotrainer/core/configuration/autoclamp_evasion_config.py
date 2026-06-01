import dataclasses

from autotrainer.core.configuration.alarm_detector import AlarmDetectorConfig
from autotrainer.core.configuration.detector import DetectorConfig


@dataclasses.dataclass
class AutoClampEvasionDetectorConfig(DetectorConfig):
    pellets_consumed_trigger: int = 3
    # how much pellets "consumed" in any way, without autoclamp engaged, to trigger the alarm detector


@dataclasses.dataclass
class AnimalEvasionAlarmConfig(AlarmDetectorConfig):

    use: bool = True
    is_emergency_condition: bool = False
