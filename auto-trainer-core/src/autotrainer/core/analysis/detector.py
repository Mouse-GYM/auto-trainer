import math
import threading
import time
from typing import Dict, Tuple, Optional

from autotrainer.core import ObservableObject, get_perf_now
from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.multiproc import no_op_timer, make_daemon_timer

logger = get_verbose_logger(__name__)


class BaseDetector(ObservableObject):

    def __init__(self):
        super().__init__()
        self._enabled = False
        self._t_started = math.nan
        self._is_engaged = False
        self._engaged_perf_c = math.nan
        self._disengaged_perf_c = math.nan
        self._cur_timer = no_op_timer
        self._lock = threading.RLock()
        self._logger = get_verbose_logger(self.__class__.__module__)

    IS_ENGAGED = "is_engaged"

    @property
    def is_engaged(self):
        return self._is_engaged

    @is_engaged.setter
    def is_engaged(self, value):
        prev, self._is_engaged = self._is_engaged, value
        if prev == value:
            return
        perf_now = get_perf_now()
        if value:
            self._engaged_perf_c = perf_now
        else:
            self._disengaged_perf_c = perf_now
        self._logger.notice("is_engaged -> %s (age previous = %.1f)",
                            value, perf_now - (self._disengaged_perf_c if value else self._engaged_perf_c))
        self._on_property_changed(self.IS_ENGAGED, value, prev)

    def _make_new_timer(self, delay: float):
        self._cur_timer.cancel()  # safer
        timer = self._cur_timer = make_daemon_timer(delay, self.check_state)
        timer.start()

    def _check_state(self) -> Optional[float]:
        raise NotImplementedError

    def check_state(self):
        with self._lock:
            if not self._enabled:
                return
            next_delay = self._check_state()
            if next_delay is not None:
                # "recurrent/timed" detector
                self._make_new_timer(next_delay)
            else:
                # detector that will resume by explicit refresh
                self._cur_timer.cancel()

    def _start(self):
        """Allow any sub-class to customize its start procedure. super() should be called."""

    def start(self):
        with self._lock:
            if self._enabled:
                return
            logger.verbose("%s: starting monitor", self.__class__.__name__)
            self._enabled = True
            self.is_engaged = False  # force reset "engaged" to False
            self._t_started = get_perf_now()
            self._start()
            self._make_new_timer(0.01)

    def _stop(self):
        pass

    def stop(self):
        with self._lock:
            if not self._enabled:
                return
            logger.verbose("%s: stopping monitor", self.__class__.__name__)
            self._enabled = False
            self._cur_timer.cancel()
            self._stop()

    def restart(self):
        self.stop()
        self.start()

    def refresh_state(self):
        """Ensure check_state is called "~now" (i.e very shortly)"""
        with self._lock:
            if not self._enabled:
                return
            self._make_new_timer(0.01)
