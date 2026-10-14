

import dataclasses

from autotrainer.core.configuration.detector import GroupSubDetectorConfig


@dataclasses.dataclass
class BoardsHardwareResetDetectorConfig(GroupSubDetectorConfig):

    allow_autoresume_on_cleared: bool = True
        # actually only happens on restart
