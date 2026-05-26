import dataclasses

from autotrainer.core.configuration.alarm_detector import AlarmDetectorConfig
from autotrainer.core.configuration.detector import DetectorConfig


@dataclasses.dataclass
class SystemFaultConfig(DetectorConfig):

    use_free_disk_space: bool = True
    auto_resume_on_free_disk_space: bool = True
    free_disk_space_min_limit_mb: int = 500

    use_watchdog: bool = True
    auto_resume_on_watchdog: bool = True
