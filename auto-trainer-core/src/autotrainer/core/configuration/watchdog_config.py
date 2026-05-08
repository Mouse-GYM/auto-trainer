
import dataclasses


@dataclasses.dataclass
class WatchdogConfig:

    timeout_trigger_delay: float = 3
