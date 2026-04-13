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
        self._config = LoadCellAutoTareConfiguration()
        self._tare_callback: Optional[TareCallbackT] = None
        self._baseline: float = 0
        self._values: numpy.ndarray
        self._index = 0
        self._reset()

    def _check_state(self) -> Optional[float]:
        # all handled by .update()
        return None

    @property
    def config(self) -> LoadCellAutoTareConfiguration:
        return self._config

    @property
    def context(self) -> LoadCellAutoTareContext:
        return self._context

    def get_context(self) -> LoadCellAutoTareContext:
        with self._lock:
            return copy.deepcopy(self._context)

    # eventual todo begin: could use instance.config.xxx instead of these individual properties
    @property
    def threshold(self) -> float:
        return self._config.threshold

    @threshold.setter
    def threshold(self, value: float) -> None:
        self._config.threshold = value

    @property
    def range_threshold(self) -> float:
        return self._config.range_threshold

    @range_threshold.setter
    def range_threshold(self, value: float) -> None:
        self._config.range_threshold = value

    @property
    def duration(self) -> float:
        return self._config.duration

    @duration.setter
    def duration(self, value: float) -> None:
        self._config.duration = value
        self._reset()

    @property
    def sample_rate(self) -> int:
        return self._config.sample_rate

    @sample_rate.setter
    def sample_rate(self, value: int) -> None:
        self._config.sample_rate = value
        self._reset()

    @property
    def baseline(self) -> float:
        return self._baseline
    # eventual todo end.

    @property
    def tare_callback(self):
        return self._tare_callback

    @tare_callback.setter
    def tare_callback(self, tare_callback: TareCallbackT) -> None:
        logger.info("Setting new tare_callback: %s", tare_callback)
        self._tare_callback = tare_callback

    def load_configuration(self, configuration: LoadCellAutoTareConfiguration):
        self._config = configuration
        self._reset()

    def save_configuration(self) -> LoadCellAutoTareConfiguration:
        return self._config

    def update(self, values: List[float]) -> bool:
        new_values = numpy.array(values)
        cur_buff = self._values
        buf_len = len(cur_buff)
        # replaces NaN by base + threshold, so that if only NaN's get in,
        # then we'll execute a tare.
        mask_nan = numpy.ma.array(new_values, mask=numpy.isnan(new_values))
        cfg = self._config
        new_values[new_values != mask_nan] = self._baseline + cfg.threshold
        increase = len(new_values)
        if increase > buf_len:
            # only keep most recent in case we get too much:
            new_values = new_values[increase - buf_len:]
            increase = buf_len

        idx = self._index
        off = idx + increase

        w_off = min(buf_len, off)
        cur_buff[idx:w_off] = new_values[:w_off - idx]
        idx += increase
        if idx >= buf_len:
            idx %= buf_len
            cur_buff[:idx] = new_values[increase - idx:]
        self._index = idx
        #
        ctx = self._context
        p_now = get_perf_now()
        ptp = float(numpy.ptp(cur_buff))
        low_ptp = ptp <= cfg.range_threshold
        if (not ctx.low_variance_engaged and low_ptp) or (ctx.low_variance_engaged and not low_ptp):
            self._logger.notice("low_variance %sengaged ; ptp=%.1f",
                                "" if low_ptp else "dis", ptp)
            with self._lock:
                ctx.low_variance_engaged = low_ptp
                if low_ptp:
                    ctx.low_variance_engaged_perf_c = p_now
                else:
                    ctx.low_variance_disengaged_perf_c = p_now

        if low_ptp and numpy.all(numpy.abs(cur_buff - self._baseline) >= cfg.threshold):
            tare_cb: Optional[Callable] = self._tare_callback
            if tare_cb is None:
                return False
            tare_cb: Callable
            if tare_cb():
                self._logger.verbose("tare_cb=True -> reset_baseline")
                self.reset_baseline()
            else:
                self._logger.verbose("tare_cb=False -> update_baseline")
                self.update_baseline()
            return True
        return False

    def update_baseline(self):
        self._baseline = float(numpy.average(self._values))

    def reset_baseline(self):
        self._baseline = 0

    def _reset(self) -> None:
        cfg = self._config
        self._values = numpy.zeros(int(cfg.sample_rate * cfg.duration))
        self._index = 0
