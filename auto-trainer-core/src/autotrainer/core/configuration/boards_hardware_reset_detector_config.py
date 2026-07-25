

import dataclasses

from autotrainer.core.configuration.detector import GroupSubDetectorConfig


@dataclasses.dataclass
class BoardsHardwareResetDetectorConfig(GroupSubDetectorConfig):

    allow_autoresume_on_cleared: bool = False
    # will require manual emergency resume, or restart (of monitor or of application)
