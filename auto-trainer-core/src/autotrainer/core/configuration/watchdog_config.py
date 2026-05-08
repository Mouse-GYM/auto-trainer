
import dataclasses


@dataclasses.dataclass
class WatchdogConfig:

    perf_counter_trigger_delay: float = 3
