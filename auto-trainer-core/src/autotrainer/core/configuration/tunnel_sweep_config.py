import dataclasses

from autotrainer.core.configuration.detector import DetectorConfig


@dataclasses.dataclass
class AutoTunnelSweepConfiguration(DetectorConfig):

    enabled: bool = False  # if False then monitor is skipping its checks
    tunnel_fan_on_duration: float = 5
    rate_limit_delay: float = 60  # seconds. minimum time between 2 sweeps

    # case 1
    misplaced_trigger_delay: float = 5  # seconds. duration pellet must be misplaced to trigger sweep

    # case 2
    recurrent_delay_minutes: float = 60  # minutes. recurrent sweep delay
