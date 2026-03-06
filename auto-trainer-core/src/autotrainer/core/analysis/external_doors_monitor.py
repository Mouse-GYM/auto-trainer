import dataclasses
import math
import threading
import time
from collections import namedtuple
from typing import Dict, Tuple, Optional, NamedTuple

from autotrainer.api.api_event_kind import ApiDetectorKind
from autotrainer.core import ObservableObject, get_perf_now, EventManager, ApiEventKind
from autotrainer.core.analysis.detector import BaseDetector
from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.configuration.external_doors_monitor_configuration import ExternalDoorsMonitorConfig
from autotrainer.core.message.system_status_message import SystemStatusMessageKind

logger = get_verbose_logger(__name__)

class DoorState(NamedTuple):
    open: Optional[bool]
    perf_c: float


FrontDoor = SystemStatusMessageKind.FRONT_DOOR
SlidingDoor = SystemStatusMessageKind.DRAWER_DOOR


ActiveDoors = {
    FrontDoor,
    SlidingDoor,
}


_door_2_api_detector_kind = {
    FrontDoor: ApiDetectorKind.frontDoor,
    SlidingDoor: ApiDetectorKind.slidingDoor,
}


@dataclasses.dataclass
class DoorsState:
    front: DoorState
    sliding: DoorState

    def get_door(self, kind: SystemStatusMessageKind) -> DoorState:
        if kind == FrontDoor:
            return self.front
        elif kind == SlidingDoor:
            return self.sliding
        raise ValueError(f"Invalid door kind: {kind}")

    def set_door(self, kind: SystemStatusMessageKind, state: DoorState):
        if kind == FrontDoor:
            self.front = state
        elif kind == SlidingDoor:
            self.sliding = state
        else:
            raise ValueError(f"Invalid door kind: {kind}")


def _make_doors_state():
    return DoorsState(
        front=DoorState(None, -math.inf),
        sliding=DoorState(None, -math.inf),
    )


class ExternalDoorsMonitor(BaseDetector):

    CONFIG = "config"

    def __init__(self, config: ExternalDoorsMonitorConfig):
        super().__init__()
        self._config = config
        self._doors_state = _make_doors_state()

    @property
    def config(self) -> ExternalDoorsMonitorConfig:
        return self._config

    @config.setter
    def config(self, value: ExternalDoorsMonitorConfig):
        prev, self._config = self._config, value
        logger.debug("external_doors=%s", value)
        # self._on_property_changed(self.CONFIG, value, prev)
        # not needed atm.

    @property
    def doors_state(self) -> DoorsState:
        return self._doors_state

    def _start(self):
        super()._start()
        self._doors_state = _make_doors_state()

    def _check_state(self):
        doors_state = self._doors_state
        perf_now = get_perf_now()
        cfg = self._config
        min_delay = math.inf
        new_engaged = False
        for door_kind in ActiveDoors:
            door_open, door_last_perf_c = doors_state.get_door(door_kind)
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

    def update_door_state(self, door_kind, is_open):
        if __debug__:
            if door_kind not in ActiveDoors:
                logger.warning("Got unexpected door message: %s", door_kind)
                return
        state = self._doors_state.get_door(door_kind)
        if is_open == state.open:
            return
        logger.notice("%s: is_open: %s -> %s", door_kind, state.open, is_open)
        new_perf_c = get_perf_now() if is_open else state.perf_c
        self._doors_state.set_door(door_kind, DoorState(is_open, new_perf_c))
        self.check_state()
        self.post_detector_event(_door_2_api_detector_kind[door_kind], is_open)
