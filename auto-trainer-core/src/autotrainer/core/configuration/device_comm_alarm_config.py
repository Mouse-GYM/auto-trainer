import dataclasses

from autotrainer.core.configuration.alarm_detector import AlarmDetectorConfig


@dataclasses.dataclass
class DeviceCommAlarmConfig(AlarmDetectorConfig):

    is_emergency_condition: bool = True
