import dataclasses

from autotrainer.core.configuration.detector import GroupSubDetectorConfig


@dataclasses.dataclass
class FreeDiskSpaceConfig(GroupSubDetectorConfig):

    min_limit_mb: int = 500  # minimum free space. if below: engage
    recheck_min_delay: float = 30  # only check max at that freq/delay
