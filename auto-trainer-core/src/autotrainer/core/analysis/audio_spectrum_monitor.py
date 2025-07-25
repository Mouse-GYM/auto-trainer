
import dataclasses
import itertools
import math
import operator
import time
from collections import deque
from functools import reduce, partial
from typing import Optional, List

from autotrainer.core import ObservableObject
from autotrainer.core.logging import get_verbose_logger


logger = get_verbose_logger(__name__)


@dataclasses.dataclass
class AudioSpectrumThrashMonitorConfig:

    time_window: float = 2
    threshold_percent: float = 80
    threshold_db: float = 10
    bins_list: List[int] = dataclasses.field(default_factory=lambda : [30, 31, 32])


class AudioSpectrumThrashMonitor(ObservableObject):

    AUDIO_THRASHING_DETECTED_PROPERTY = 'audio_thrashing_detected'

    def __init__(
        self,
        *,
        config: AudioSpectrumThrashMonitorConfig = AudioSpectrumThrashMonitorConfig()
    ):
        super().__init__()
        self._config = config
        self._values_history = deque()
        self._cur_detected = False
        self._t_start_detecting: Optional[float] = None
        self._t_next_report: float = time.time()

    @property
    def is_thrashing_detected(self):
        return self._cur_detected

    @is_thrashing_detected.setter
    def is_thrashing_detected(self, value):
        self._cur_detected = self._on_property_changed(self.AUDIO_THRASHING_DETECTED_PROPERTY, value, self._cur_detected)

    def _update_history(self, values, when, index):
        hist = self._values_history
        dropped = 0
        while len(hist) > 0:
            h0_when = hist[0][1]
            # we could actually use a dichotomic lookup/search, assuming the "when" are consistent (always increasing)
            # and drop all up to the "middle" point in 1 operation.
            if when - h0_when <= self._config.time_window:
                break
            hist.popleft()
            dropped += 1
        hist.append(([values[i] for i in self._config.bins_list], when, index))
        if __debug__:
            t_now = time.time()
            if t_now > self._t_next_report:
                self._t_next_report += 60
                logger.debug("hist size=%s cur_dropped=%s", len(hist), dropped)

    def update(self, values: List[float], when: float = 0.0, index: int = 0):
        self._update_history(values, when, index)
        cfg = self._config
        above_threshold = list(
            map(
                partial(operator.le, cfg.threshold_db),
                itertools.chain(*(v[0] for v in self._values_history))
            )
        )
        percent = 100 * sum(map(int, above_threshold)) / len(above_threshold)
        detected = percent >= cfg.threshold_percent
        t_start = self._t_start_detecting
        if detected:
            if t_start is None:
                self._t_start_detecting = when
                detected = False
            else:
                detected = when - t_start >= cfg.time_window
        else:
            if t_start is not None:
                self._t_start_detecting = None
        self.is_thrashing_detected = detected
