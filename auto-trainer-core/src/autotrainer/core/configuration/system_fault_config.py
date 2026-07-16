import dataclasses

from autotrainer.core.configuration.alarm_detector import AlarmDetectorConfig
from autotrainer.core.configuration.boards_hardware_reset_detector_config import BoardsHardwareResetDetectorConfig
from autotrainer.core.configuration.free_disk_space_config import FreeDiskSpaceConfig
from autotrainer.core.configuration.watchdog_config import WatchdogConfig


@dataclasses.dataclass
class SystemFaultConfig(AlarmDetectorConfig):

    free_disk_space: FreeDiskSpaceConfig = dataclasses.field(default_factory=FreeDiskSpaceConfig)
    boards_hardware_reset: BoardsHardwareResetDetectorConfig = dataclasses.field(default_factory=BoardsHardwareResetDetectorConfig)

    # watchdog: WatchdogConfig = dataclasses.field(default_factory=WatchdogConfig)
    # currently at system-config top-level
