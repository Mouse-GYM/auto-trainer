import math
import threading
import time
from typing import Dict, Tuple, Optional

from autotrainer.core import ObservableObject
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

    IS_ENGAGED = "is_engaged"

    @property
    def is_engaged(self):
        return self._is_engaged

    @is_engaged.setter
    def is_engaged(self, value):
        prev, self._is_engaged = self._is_engaged, value
        if prev == value:
            return
        perf_now = time.perf_counter()
        if value:
            self._engaged_perf_c = perf_now
        else:
            self._disengaged_perf_c = perf_now
        logger.notice("%s: is_engaged -> %s (age previous = %.1f)",
                      self.__class__.__name__, value, perf_now - (self._disengaged_perf_c if value else self._engaged_perf_c))
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
                self._make_new_timer(next_delay)
            else:
                self._cur_timer.cancel()

    def _start(self):
        pass

    def start(self):
        with self._lock:
            if self._enabled:
                return
            logger.verbose("%s: starting monitor", self.__class__.__name__)
            self._enabled = True
            self._t_started = time.perf_counter()
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
        """Ensure check_state is called "~now" (i.e very shortly)
        This monitor can effectively uses very long timer. which must be cancelled,
         in order for a new one to be created.
        """
        with self._lock:
            if not self._enabled:
                return
            self._make_new_timer(0.01)
