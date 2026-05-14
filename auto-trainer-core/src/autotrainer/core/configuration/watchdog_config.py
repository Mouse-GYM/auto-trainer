
import dataclasses


@dataclasses.dataclass
class WatchdogConfig:

    timeout_trigger_delay: float = 5  # seconds
    # if watchdog perf counter older than this then trigger watchdog
