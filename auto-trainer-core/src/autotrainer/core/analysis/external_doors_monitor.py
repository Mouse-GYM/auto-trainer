import math
import threading
import time
from typing import Dict, Tuple, Optional

from autotrainer.core import ObservableObject
from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.configuration.external_doors_monitor_configuration import ExternalDoorsMonitorConfig
from autotrainer.core.message.system_status_message import SystemStatusMessageKind
from autotrainer.core.multiproc import no_op_timer, make_daemon_timer

logger = get_verbose_logger(__name__)


DoorsStateT = Dict[SystemStatusMessageKind, Tuple[Optional[float], Optional[float]]]


ActiveDoors = {
    SystemStatusMessageKind.FRONT_DOOR,
    SystemStatusMessageKind.DRAWER_DOOR,
}


def _make_external_doors_state() -> DoorsStateT:
    return {
        door: (None, None)
        for door in ActiveDoors
    }


class ExternalDoorsMonitor(ObservableObject):

    def __init__(self, config: ExternalDoorsMonitorConfig):
        super().__init__()
        self._config = config
        self._enabled = False
        self._t_started = math.nan
        self._is_engaged = False
        self._engaged_perf_c = math.nan
        self._disengaged_perf_c = math.nan
        self._lock = threading.RLock()
        self._doors_state: DoorsStateT = _make_external_doors_state()
        self._cur_timer = no_op_timer

    #

    CONFIG = "config"

    @property
    def config(self) -> ExternalDoorsMonitorConfig:
        return self._config

    @config.setter
    def config(self, value: ExternalDoorsMonitorConfig):
        prev, self._config = self._config, value
        logger.debug("external_doors=%s", value)
        # self._on_property_changed(self.CONFIG, value, prev)
        # not needed atm.

    #

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
            if not prev:
                self._engaged_perf_c = perf_now
        else:
            if prev:
                self._disengaged_perf_c = perf_now
        if value != prev:
            logger.notice("is_engaged -> %s", value)
        self._on_property_changed(self.IS_ENGAGED, value, prev)

    #

    def start(self, *, reason: str = "na"):
        with self._lock:
            if self._enabled:
                return
            self._cur_timer.cancel()  # safer (or required if there is/was a real timer, actually).
            logger.verbose("starting monitor: %s", reason)
            self._enabled = True
            self._t_started = time.perf_counter()
            self._doors_state = _make_external_doors_state()
            timer = self._cur_timer = make_daemon_timer(0.1, self.check_state)
            timer.start()

    def stop(self, *, reason: str = "na"):
        with self._lock:
            if not self._enabled:
                return
            logger.verbose("stopping monitor: %s", reason)
            self._enabled = False
            self._cur_timer.cancel()

    def restart(self, *, reason: str = "na"):
        self.stop(reason=reason)
        self.start(reason=reason)

    def check_state(self):
        with self._lock:
            self._check_state()

    def _check_state(self):
        if not self._enabled:
            return
        doors_state = self._doors_state
        perf_now = time.perf_counter()
        cfg = self._config
        new_engaged = (
            perf_now - self._t_started >= cfg.trigger_open_delay
            and all(
                door_open and door_last_perf_c is not None and perf_now - door_last_perf_c >= cfg.trigger_open_delay
                for door_open, door_last_perf_c in (
                    doors_state[active_door]
                    # NB: using indexing on the doors state dict is greatly safer, than iterating over it,
                    # if it would be modified by another thread at the same time.
                    for active_door in ActiveDoors
                )
            )
        )
        self.is_engaged = new_engaged
        # retry in 1s:
        timer = self._cur_timer = make_daemon_timer(1, self.check_state)
        timer.start()

    def update_door_state(self, door, is_open):
        if door not in ActiveDoors:
            logger.warning("Got unexpected door message: %s", door)
            return
        # with self._lock:
        doors_state = self._doors_state
        # taking lock not required here, given using dict lookup and set, AND given the check_state timer,
        # also does as well, and also given the dict keys never change.
        prev_open, prev_perf_c = doors_state[door]
        if is_open != prev_open:
            logger.notice("%s: is_open: %s -> %s", door, prev_open, is_open)
            new_perf_c = time.perf_counter() if is_open else prev_perf_c
            doors_state[door] = (is_open, new_perf_c)
            # don't call check_state: it's a recurrent timer
