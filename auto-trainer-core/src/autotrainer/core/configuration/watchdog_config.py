
import dataclasses
from typing import Optional

from autotrainer.core.configuration.detector import GroupSubDetectorConfig


@dataclasses.dataclass
class WatchdogConfig(GroupSubDetectorConfig):

    timeout_trigger_delay: float = 5  # seconds
    # if watchdog perf counter older than this then trigger watchdog


@dataclasses.dataclass
class WatchdogItemDetectorConfig(GroupSubDetectorConfig):

    override_timeout_trigger_delay: Optional[float] = None
