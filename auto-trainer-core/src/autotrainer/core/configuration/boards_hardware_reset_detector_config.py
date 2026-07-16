

import dataclasses

from autotrainer.core.configuration.alarm_detector import AlarmDetectorConfig


@dataclasses.dataclass
class BoardsHardwareResetDetectorConfig(AlarmDetectorConfig):

    is_emergency_condition: bool = True
    allow_autoresume_on_cleared: bool = False
