import dataclasses

from autotrainer.core.configuration.detector import DetectorConfig


@dataclasses.dataclass
class AutoTunnelSweepConfiguration(DetectorConfig):
    enabled: bool = False
    misplaced_trigger_delay: float = 5
    tunnel_fan_on_duration: float = 5
    rate_limit_delay: float = 60
