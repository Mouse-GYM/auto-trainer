import math
import queue
import threading
import time
from typing import Dict, Tuple, Optional, Union

from autotrainer.api import ApiEventKind
from autotrainer.core import ObservableObject, get_perf_now, EventManager
from autotrainer.core.event import post_api_detector_event_content
from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.multiproc import no_op_timer, make_daemon_timer


logger = get_verbose_logger(__name__)


class BaseDetector(ObservableObject):

    IS_ENGAGED = "is_engaged"

    use_daemon: bool = False
    default_timer_delay: Optional[float] = None

    def __init__(self):
        super().__init__()
        self._running = False
        self._p_started = -math.inf
        self._is_engaged = False
        self._engaged_perf_c = -math.inf
        self._disengaged_perf_c = -math.inf
        self._cur_timer = no_op_timer
        self._thread_queue: Optional[Tuple[threading.Thread, queue.Queue]] = None
        self._lock = threading.RLock()
        self._logger = get_verbose_logger(self.__class__.__module__)
        self._event_manager = EventManager.default()

    def post_detector_event(self, detector_id: int, active: bool, enabled: Optional[bool] = None):
        if enabled is None:
            enabled = self._running
        post_api_detector_event_content(self._event_manager, detector_id, active, enabled)

    @property
    def running(self):
        return self._running

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

    @property
    def engaged_age(self):
        return (get_perf_now() if self._is_engaged else self._disengaged_perf_c) - self._engaged_perf_c

    @property
    def disengaged_age(self):
        return (get_perf_now() if not self._is_engaged else self._engaged_perf_c) - self._disengaged_perf_c

    def _make_new_timer(self, delay: float):
        self._cur_timer.cancel()  # safer
        timer = self._cur_timer = make_daemon_timer(delay, self.check_state)
        timer.start()
        self._logger.verbose("created timer to check_state within %.1fs", delay)

    def _check_state(self) -> Optional[float]:
        raise NotImplementedError

    def check_state_if_not_detector_thread(self):
        th_q = self._thread_queue
        if th_q is None or threading.current_thread() != th_q[0]:
            self.check_state()

    def check_state(self):
        with self._lock:
            if not self._running:
                return None
            next_delay = self._check_state()
            if next_delay is None:
                next_delay = self.default_timer_delay
            if next_delay is not None and not self.use_daemon:
                # "recurrent/timed" detector
                self._make_new_timer(next_delay)
            else:
                # daemon detector or detector that will resume by explicit refresh
                self._cur_timer.cancel()
                self._cur_timer = no_op_timer
        return next_delay

    def _start(self):
        """Allow any subclass to customize its start procedure. super() should be called."""

    def start(self):
        with self._lock:
            if self._running:
                self._logger.debug("requested start but already running")
                return
            self._logger.verbose("%s: starting monitor", self.__class__.__name__)
            self._running = True
            self.is_engaged = False  # force reset "engaged" to False
            self._p_started = get_perf_now()
            self._start()
            if self.use_daemon:
                cmd_queue = queue.Queue()
                thread = threading.Thread(name=self.__class__.__name__, target=self._daemon_run, daemon=True,
                                          args=(cmd_queue,))
                thread.start()
                self._thread_queue = thread, cmd_queue
            else:
                self.check_state()

    def _daemon_run(self, cmd_queue):
        self._logger.info("%s running", self.__class__.__name__)
        while True:
            delay = self.check_state()  # always check immediately
            if delay is None:
                delay = self.default_timer_delay
                if delay is None:
                    delay = 1
            # Now limit max delay to 60 seconds,
            # so that any change in config will be handled at most every 60 seconds.
            # Some detector, like global animal presence, could use very long delay between check,
            # so this ensures that if its setting relating to the delay is changed, then the new one will be handled,
            # ~relatively quickly.
            # Otherwise, we would need to restart any of them that has its config updated.
            delay = min(60., delay)
            try:
                r = cmd_queue.get(timeout=delay)
            except queue.Empty:
                pass
            else:
                cmd_queue.task_done()
                # we only support None exit sentinel
                assert r is None
                break
        self._logger.verbose("%s: exiting main loop", self.__class__.__name__)

    def _stop(self):
        pass

    def stop(self):
        with self._lock:
            self._cur_timer.cancel()
            if not self._running:
                return
            self._logger.verbose("%s: stopping monitor", self.__class__.__name__)
            self._running = False
            self._stop()
        # don't try join check thread with the lock acquired, given that can deadlock otherwise.
        thread_queue = self._thread_queue
        if thread_queue is not None:
            thread, q = self._thread_queue
            # assert isinstance(q, queue.Queue)
            if thread.is_alive():
                q.put(None)
            self._logger.debug("Joining check thread %s", thread)
            thread.join(3)
            self._logger.verbose("joined check thread %s", thread)
            if thread.is_alive():
                self._logger.warning("check thread still alive, but continuing anyway")
            self._thread_queue = None

    def restart(self):
        self._logger.notice("Restarting %s", self.__class__.__name__)
        self.stop()
        self.start()
