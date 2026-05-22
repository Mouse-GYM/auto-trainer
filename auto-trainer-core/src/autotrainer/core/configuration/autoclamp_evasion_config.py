import dataclasses

from autotrainer.core.configuration.alarm_detector import AlarmDetectorConfig


@dataclasses.dataclass
class AutoClampEvasionAlarmConfig(AlarmDetectorConfig):

    use: bool = True
    is_emergency_condition: bool = False

    pellets_consumed_trigger: int = 3
    # how much pellets "consumed" in any way, without autoclamp engaged, to trigger the alarm detector
