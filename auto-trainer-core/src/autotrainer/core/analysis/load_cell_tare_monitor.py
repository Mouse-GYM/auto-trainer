import copy
import dataclasses
import math
import os
import time
from typing import Callable, Optional, List, Protocol

import numpy

from autotrainer.core import get_perf_now
from autotrainer.core.analysis.detector import BaseDetector
from autotrainer.core.configuration.load_cell_config import LoadCellAutoTareConfiguration
from autotrainer.core.logging import get_verbose_logger

logger = get_verbose_logger(__name__)


class TareCallbackT(Protocol):

    def __call__(self, *, force: bool = False) -> bool:
        """Request a tare if possible, or force it
        If tare callback returns True: reset_baseline, otherwise: update_baseline
        """


@dataclasses.dataclass
class LoadCellAutoTareContext:
    low_variance_engaged: bool = True
    low_variance_engaged_perf_c: float = -math.inf
    low_variance_disengaged_perf_c: float = -math.inf


class LoadCellTareMonitor(BaseDetector[LoadCellAutoTareConfiguration]):
    """
    Monitor the load cell data stream and whether zeroing is required.  The decision to actually zero or not is not
    performed here.  It simply reports whether the conditions meet the requirements where zeroing is applicable.
    """

    config_cls = LoadCellAutoTareConfiguration

    def __init__(self):
        super().__init__()
        self._context = LoadCellAutoTareContext()
        self._tare_callback: Optional[TareCallbackT] = None
        self._baseline: float = 0
        self._values: numpy.ndarray
        self._index = 0
        self._reset()
        # debug:
        self._next_dbg_log = -math.inf
        self._last_dbg_log = -math.inf
        self._cnt_received = 0

    def _check_state(self) -> Optional[float]:
        # all handled by .update()
        return None

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

    def _set_config(self, config: LoadCellAutoTareConfiguration):
        super()._set_config(config)
        self._reset()

    def save_configuration(self) -> LoadCellAutoTareConfiguration:
        return self._config

    def update(self, values: List[float]) -> bool:
        log = self._logger
        new_values = numpy.array(values)
        t_now = time.perf_counter()
        cur_buff = self._values
        buf_len = len(cur_buff)
        increase = len(new_values)
        if increase > buf_len:
            # only keep most recent in case we get too much:
            new_values = new_values[increase - buf_len:]
            increase = buf_len
        self._cnt_received += increase

        cfg = self._config
        # replaces NaN by base + 2 * threshold, so that if only NaN's get in,
        # NB: using 2 * threshold to be sure to be above it for below comparison against it.
        # so that if all of them are NaN we'll execute a tare.
        mask_nan = numpy.ma.array(new_values, mask=numpy.isnan(new_values))
        is_all_nans = bool(numpy.isnan(new_values).all())
        has_nans = bool(numpy.isnan(new_values).any())
        new_values[new_values != mask_nan] = self._baseline + 2 * cfg.threshold

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
        #
        if __debug__:
            if t_now > self._next_dbg_log or has_nans:
                rcv_per_s = self._cnt_received / (t_now - self._last_dbg_log)
                log.verbose(
                    "base=%.1f low_ptp=%s new values: received=%.1f/s cur_values=%s ; buffer=%s",
                    self._baseline, low_ptp, rcv_per_s, new_values, cur_buff.tolist(),
                )
                self._last_dbg_log = t_now
                self._next_dbg_log = t_now + float(os.getenv("LOADCELL_TARE_DBG_DELAY", 30))
                self._cnt_received = 0

        #
        if (not ctx.low_variance_engaged and low_ptp) or (ctx.low_variance_engaged and not low_ptp):
            log.notice("low_variance %sengaged ; ptp=%.1f",
                                "" if low_ptp else "dis", ptp)
            with self._lock:
                ctx.low_variance_engaged = low_ptp
                if low_ptp:
                    ctx.low_variance_engaged_perf_c = p_now
                else:
                    ctx.low_variance_disengaged_perf_c = p_now

        if is_all_nans or (low_ptp and numpy.all(numpy.abs(cur_buff - self._baseline) >= cfg.threshold)):
            tare_cb = self._tare_callback
            if tare_cb is None:
                log.debug("no tare callback configured")
                return False
            tare_cb: TareCallbackT
            if tare_cb(force=is_all_nans):
                log.verbose("tare_cb=True -> reset_baseline")
                self.reset_baseline()
            else:
                if is_all_nans:
                    self.reset_baseline()
                    log.verbose("all nans: reset_baseline")
                else:
                    self.update_baseline()
                    log.verbose("tare_cb=False -> update_baseline")
            # replace all values in current buffer with baseline:
            self._values[:] = self._baseline
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
