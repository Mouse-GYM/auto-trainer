
import dataclasses
import itertools
import math
import operator
import os
import time
from collections import deque
from functools import reduce, partial
from typing import Optional, List

from autotrainer.core import ObservableObject
from autotrainer.core.logging import get_verbose_logger


logger = get_verbose_logger(__name__)


@dataclasses.dataclass
class AudioSpectrumThrashMonitorConfig:

    time_window: float = 0.5
    threshold_percent: float = 50
    threshold_db: float = 130
    # NB: the values we read from CAN bus are supposedly (or we consider them as is) in dB unit.
    # but the current value range we get/read is ~80-85 up to ~140-145, generally around ~100 for non-noisy.
    bins_list: List[int] = dataclasses.field(default_factory=lambda : [3, 4, 5, 6])
    # NB:
    # with 6kHz: 3/4/5  goes from ~110 -> ~140
    # with 8kHz: 3 goes from ~100-100 to ~135 and 5/6 goes from ~110 -> ~140


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
        perf_now = time.perf_counter()
        self._last_engaged_perf_c: float = perf_now
        self._last_disengaged_perf_c: float = perf_now
        self._when_start_detecting: Optional[float] = None
        self._t_perf_next_report: float = perf_now
        self._when_next_check: float = 0

    @property
    def config(self):
        return self._config

    @config.setter
    def config(self, value):
        self._config = value

    @property
    def is_thrashing_detected(self):
        return self._cur_detected

    @is_thrashing_detected.setter
    def is_thrashing_detected(self, value):
        prev, self._cur_detected = self._cur_detected, value
        if prev != value:
            perf_now = time.perf_counter()
            if value:
                self._last_engaged_perf_c = perf_now
            else:
                self._last_disengaged_perf_c = perf_now
            self._on_property_changed(self.AUDIO_THRASHING_DETECTED_PROPERTY, value, prev)

    @property
    def engaged_age(self):
        return (time.perf_counter() if self._cur_detected else self._last_disengaged_perf_c) - self._last_engaged_perf_c

    @property
    def disengaged_age(self):
        return (time.perf_counter() if not self._cur_detected else self._last_engaged_perf_c) - self._last_disengaged_perf_c

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
        hist.append((values, when, index))
        if __debug__:
            t_perf_now = time.perf_counter()
            if t_perf_now > self._t_perf_next_report:
                self._t_perf_next_report = t_perf_now + float(os.getenv("AUDIO_THRASHING_LOG_REPORT_DELAY", "60"))
                logger.debug("hist size=%s cur_dropped=%s cur_when=%.3f cur_index=%s ; values=%s",
                             len(hist), dropped, when, index, [[f"{vv:.1f}" for vv in v[0]] for v in hist])

    def update(self, values: List[float], when: float = 0.0, index: int = 0):
        cfg = self._config
        v2 = [values[idx] for idx in cfg.bins_list]
        self._update_history(v2, when, index)
        is_above_thresh = partial(operator.le, cfg.threshold_db)
        cur_above_pc = sum(map(is_above_thresh, v2)) * 100 / len(cfg.bins_list)
        cur_value_avg = sum(v2) / len(cfg.bins_list)
        t_start = self._when_start_detecting
        if cur_value_avg >= cfg.threshold_db or cur_above_pc >= cfg.threshold_percent:
            if t_start is None:
                self._when_start_detecting = when
                self._when_next_check = when + cfg.time_window / 2
                return
        if when < self._when_next_check:
            return
        self._when_next_check = when + cfg.time_window / 2
        values_history = self._values_history
        avg_value = (
            sum(itertools.chain(*(v[0] for v in values_history)))
            / len(values_history)
            / len(cfg.bins_list)
        )
        above_threshold = list(map(is_above_thresh, itertools.chain(*(v[0] for v in self._values_history))))
        percent = 100 * sum(map(int, above_threshold)) / len(above_threshold)
        detected = percent >= cfg.threshold_percent or avg_value >= cfg.threshold_db
        if detected != self.is_thrashing_detected:
            logger.verbose("Thrashing change detected: %s avg=%.1f above_pc=%.1f ; %s",
                           detected, avg_value, percent, values_history)
            self.is_thrashing_detected = detected
            if detected:
                while len(values_history) > 1:
                    values_history.popleft()
            else:
                self._when_start_detecting = None
