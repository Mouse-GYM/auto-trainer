import dataclasses

from autotrainer.core.configuration.alarm_detector import AlarmDetectorConfig


@dataclasses.dataclass
class PresenceInCageAlarmConfig(AlarmDetectorConfig):

    tunnel_to_cage_presence_missing_delay: float = 5
