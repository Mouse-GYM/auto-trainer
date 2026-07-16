import dataclasses

from autotrainer.core.configuration.alarm_detector import AlarmDetectorConfig


@dataclasses.dataclass
class FreeDiskSpaceConfig(AlarmDetectorConfig):

    min_limit_mb: int = 500

