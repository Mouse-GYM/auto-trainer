import math
import threading
import time
from typing import Dict, Tuple, Optional

from autotrainer.core import ObservableObject, get_perf_now
from autotrainer.core.analysis.detector import BaseDetector
from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.configuration.external_doors_monitor_configuration import ExternalDoorsMonitorConfig
from autotrainer.core.message.system_status_message import SystemStatusMessageKind
from autotrainer.core.multiproc import no_op_timer, make_daemon_timer

logger = get_verbose_logger(__name__)


DoorsStateT = Dict[SystemStatusMessageKind, Tuple[Optional[bool], Optional[float]]]


ActiveDoors = {
    SystemStatusMessageKind.FRONT_DOOR,
    SystemStatusMessageKind.DRAWER_DOOR,
}


def _make_external_doors_state() -> DoorsStateT:
    return {
        door: (None, None)
        for door in ActiveDoors
    }


class ExternalDoorsMonitor(BaseDetector):

    def __init__(self, config: ExternalDoorsMonitorConfig):
        super().__init__()
        self._config = config
        self._doors_state: DoorsStateT = _make_external_doors_state()

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

    def _start(self):
        super()._start()
        self._doors_state = _make_external_doors_state()

    def _check_state(self):
        doors_state = self._doors_state
        perf_now = get_perf_now()
        cfg = self._config
        min_delay = math.inf
        new_engaged = False
        for door in ActiveDoors:
            door_open, door_last_perf_c = doors_state[door]
            if door_open:
                r = cfg.trigger_open_delay - (perf_now - door_last_perf_c)
                if r < 0:
                    new_engaged = True
                elif r < min_delay:
                    min_delay = r
        self.is_engaged = new_engaged
        if not new_engaged and not math.isinf(min_delay):
            logger.debug("timer for next check state delay=%.1f", min_delay)
            return min_delay
        return None

    def update_door_state(self, door, is_open):
        if __debug__:
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
            new_perf_c = get_perf_now() if is_open else prev_perf_c
            doors_state[door] = (is_open, new_perf_c)
            self.refresh_state()
