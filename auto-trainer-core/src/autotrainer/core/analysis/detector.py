import math
import queue
import threading
import time
from typing import Dict, Tuple, Optional, Union

from autotrainer.core import ObservableObject, get_perf_now
from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.multiproc import no_op_timer, make_daemon_timer


logger = get_verbose_logger(__name__)


class BaseDetector(ObservableObject):

    use_daemon: bool = False
    default_timer_delay: Optional[float] = None

    def __init__(self):
        super().__init__()
        self._running = False
        self._t_started = math.nan
        self._is_engaged = False
        self._engaged_perf_c = math.nan
        self._disengaged_perf_c = math.nan
        self._cur_timer = no_op_timer
        self._thread_queue: Optional[Tuple[threading.Thread, queue.Queue]] = None
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
            if not self._running:
                return
            next_delay = self._check_state()
            if next_delay is None:
                next_delay = self.default_timer_delay
            if next_delay is not None and not self.use_daemon:
                # "recurrent/timed" detector
                self._make_new_timer(next_delay)
            else:
                # detector that will resume by explicit refresh
                self._cur_timer.cancel()
                self._cur_timer = no_op_timer

    def _start(self):
        """Allow any sub-class to customize its start procedure. super() should be called."""

    def start(self):
        with self._lock:
            if self._running:
                return
            self._logger.verbose("%s: starting monitor", self.__class__.__name__)
            self._running = True
            self.is_engaged = False  # force reset "engaged" to False
            self._t_started = get_perf_now()
            self._start()
            if self.use_daemon:
                cmd_queue = queue.Queue()
                thread = threading.Thread(name=self.__class__.__name__, target=self._daemon_run, daemon=True,
                                          args=(cmd_queue,))
                thread.start()
                self._thread_queue = thread, cmd_queue
            else:
                self.check_state()
                # self._make_new_timer(0.01)

    def _daemon_run(self, cmd_queue):
        while True:
            delay = self.default_timer_delay
            if delay is None or delay <= 0.1:
                delay = 0.1
            try:
                r = cmd_queue.get(timeout=delay)
                assert r is None  # we only support None exit sentinel
                break
            except queue.Empty:
                pass
            self.check_state()

    def _stop(self):
        pass

    def stop(self):
        with self._lock:
            if not self._running:
                return
            self._logger.verbose("%s: stopping monitor", self.__class__.__name__)
            self._running = False
            self._cur_timer.cancel()
            self._stop()
            thread_queue = self._thread_queue
            if thread_queue is not None:
                thread, q = self._thread_queue
                q.put(None)
                self._logger.debug("Joining thread")
                thread.join()
                self._thread_queue = None

    def restart(self):
        self.stop()
        self.start()

    def refresh_state(self):
        """Ensure check_state is called "~now" (i.e very shortly)"""
        with self._lock:
            if not self._running:
                return
            # self._make_new_timer(0.01)  # todo: could call self.check_state() directly instead
            self.check_state()
