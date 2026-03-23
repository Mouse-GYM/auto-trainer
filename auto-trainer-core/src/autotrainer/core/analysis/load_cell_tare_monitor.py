import copy
import dataclasses
import math
from typing import Callable, Optional, List

import numpy

from autotrainer.core import get_perf_now
from autotrainer.core.analysis.detector import BaseDetector
from autotrainer.core.configuration.load_cell_config import LoadCellAutoTareConfiguration
from autotrainer.core.logging import get_verbose_logger

logger = get_verbose_logger(__name__)


TareCallbackT = Optional[Callable[[], bool]]



@dataclasses.dataclass
class LoadCellAutoTareContext:
    low_variance_engaged: bool = True
    low_variance_engaged_perf_c: float = -math.inf
    low_variance_disengaged_perf_c: float = -math.inf


class LoadCellTareMonitor(BaseDetector):
    """
    Monitor the load cell data stream and whether zeroing is required.  The decision to actually zero or not is not
    performed here.  It simply reports whether the conditions meet the requirements where zeroing is applicable.
    """

    def __init__(self):
        super().__init__()

        self._context = LoadCellAutoTareContext()

        self._threshold: float = 0.1
        self._range_threshold: float = 0.5
        self._duration: float = 2.0
        self._sample_rate: int = 100

        self._baseline: float = 0
        self._buffer_len = 0
        self._values = None
        self._index = 0

        self._tare_callback: Optional[TareCallbackT] = None

        self._reset()

    @property
    def context(self) -> LoadCellAutoTareContext:
        return self._context

    def get_context(self) -> LoadCellAutoTareContext:
        with self._lock:
            return copy.deepcopy(self._context)

    @property
    def threshold(self) -> float:
        return self._threshold

    @threshold.setter
    def threshold(self, value: float) -> None:
        self._threshold = value

    @property
    def range_threshold(self) -> float:
        return self._range_threshold

    @range_threshold.setter
    def range_threshold(self, value: float) -> None:
        self._range_threshold = value

    @property
    def duration(self) -> float:
        return self._duration

    @duration.setter
    def duration(self, value: float) -> None:
        self._duration = value
        self._reset()

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @sample_rate.setter
    def sample_rate(self, value: int) -> None:
        self._sample_rate = value
        self._reset()

    @property
    def baseline(self) -> float:
        return self._baseline

    @property
    def tare_callback(self):
        return self._tare_callback

    @tare_callback.setter
    def tare_callback(self, tare_callback: TareCallbackT) -> None:
        logger.info("Setting new tare_callback: %s", tare_callback)
        self._tare_callback = tare_callback

    def load_configuration(self, configuration: LoadCellAutoTareConfiguration):
        self._threshold = configuration.threshold
        self._range_threshold = configuration.range_threshold
        self._duration = configuration.duration
        self._reset()

    def save_configuration(self) -> LoadCellAutoTareConfiguration:
        return LoadCellAutoTareConfiguration(
            threshold=self._threshold,
            range_threshold=self._range_threshold,
            duration=self._duration
        )

    def update(self, values: List[float]) -> bool:
        # Currently there is no state management or other reason to perform the calculation if there is no callback.
        increase = len(values)
        self._values[self._index:self._index + increase] = numpy.array(values)
        self._index += increase
        if self._index >= self._buffer_len:
            self._index = 0
        #
        ctx = self._context
        p_now = get_perf_now()
        ptp = numpy.ptp(self._values)
        low_ptp = ptp <= self._range_threshold
        if (not ctx.low_variance_engaged and low_ptp) or (ctx.low_variance_engaged and not low_ptp):
            self._logger.notice("low_variance %sengaged ; ptp=%.1f ; values=%s",
                                "" if low_ptp else "dis", ptp, self._values)
            with self._lock:
                ctx.low_variance_engaged = low_ptp
                if low_ptp:
                    ctx.low_variance_engaged_perf_c = p_now
                else:
                    ctx.low_variance_disengaged_perf_c = p_now

        if (
            numpy.all(numpy.abs(self._values - self._baseline) > self._threshold)
            and low_ptp
        ):
            tare_cb = self._tare_callback
            if tare_cb is None:
                return False
            if tare_cb():
                self._logger.verbose("tare_cb=True -> reset_baseline")
                self.reset_baseline()
            else:
                self._logger.verbose("tare_cb=False -> update_baseline")
                self.update_baseline()
            return True
        return False

    def update_baseline(self):
        self._baseline = numpy.average(self._values)

    def reset_baseline(self):
        self._baseline = 0

    def _reset(self) -> None:
        self._buffer_len = int(self._sample_rate * self._duration)
        self._values = numpy.zeros(self._buffer_len)
        self._index = 0
