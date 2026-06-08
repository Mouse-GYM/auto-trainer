import dataclasses
from typing import List

from autotrainer.core.configuration.detector import DetectorConfig


@dataclasses.dataclass
class AudioSpectrumThrashMonitorConfig(DetectorConfig):

    time_window: float = 0.5
    threshold_percent: float = 50
    threshold_db: float = 130
    # NB: the values we read from CAN bus are supposedly (or we consider them as is) in dB unit.
    # but the current value range we get/read is ~80-85 up to ~140-145, generally around ~100 for non-noisy.
    bins_list: List[int] = dataclasses.field(default_factory=lambda : [3, 4, 5, 6])
    # NB:
    # with 6kHz: 3/4/5  goes from ~110 -> ~140
    # with 8kHz: 3 goes from ~100-100 to ~135 and 5/6 goes from ~110 -> ~140
