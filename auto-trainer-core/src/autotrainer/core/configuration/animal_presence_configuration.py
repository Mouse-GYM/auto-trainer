import dataclasses

from autotrainer.core.configuration.alarm_detector import AlarmDetectorConfig
from autotrainer.core.configuration.detector import DetectorConfig


@dataclasses.dataclass
class GlobalAnimalPresenceConfig(AlarmDetectorConfig):

    presence_missing_delay_hours: float = 12
    # if mouse not seen in tunnel AND not seen in cage longer than the delay, then trigger
