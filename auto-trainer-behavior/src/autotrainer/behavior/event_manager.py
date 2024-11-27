from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, IntEnum
from typing import Optional

from autotrainer.core import ProjectInfo, ProjectInterval


class BehaviorEventKind(IntEnum, Enum):
    tunnelEnter = 1001
    tunnelExit = 1002,
    loadCellActive = 1101
    loadCellInactive = 1102,
    pelletLoadCan = 1201
    pelletLoadBegin = 1202,
    pelletLoadEnd = 1203,
    pelletSendCan = 1204
    pelletSendBegin = 1205,
    pelletSendEnd = 1206,
    pelletCoverCan = 1207
    pelletCoverBegin = 1208,
    pelletCoverEnd = 1209,
    pelletReleaseCan = 1210
    pelletReleaseBegin = 1211,
    pelletReleaseEnd = 1212,
    pelletAcknowledgeToken = 1298,
    pelletExternalToken = 1299,
    sessionStarted = 1301,
    sessionEnded = 1302,
    sessionPelletIncrease = 1311,
    sessionPelletDecrease = 1312,
    sessionMouseSeen = 1321,
    dayStarted = 1401,
    dayIncreasePellet = 1411,
    dayDecreasePellet = 1412


@dataclass(frozen=True)
class EventInfo:
    kind: BehaviorEventKind
    when: datetime = None
    index: int = None
    context: object = None


logger = logging.getLogger(__name__)


class EventManager:
    _instance = None

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = EventManager("EventManagerInstance")

        return cls._instance

    def __init__(self, key=""):
        if key != "EventManagerInstance":
            raise Exception("Use EventManager.instance()")

        self._project_info = None
        self._event_file = None
        self._last_event_info: Optional[EventInfo] = None
        self._repeat_event_count = 0

    @property
    def project(self) -> ProjectInfo:
        return self._project_info

    @project.setter
    def project(self, value: ProjectInfo):
        self._project_info = value

        self._update_event_file()

    def flush(self):
        if self._event_file is not None:
            self._event_file.flush()

    def post_event(self, info: BehaviorEventKind | EventInfo):
        if isinstance(info, BehaviorEventKind):
            info = EventInfo(info)

        if self._last_event_info and info.kind == self._last_event_info.kind and info.context == self._last_event_info.context:
            self._repeat_event_count += 1
            return

        if self._repeat_event_count > 0:
            self._write_event(self._last_event_info, self._repeat_event_count)
            self._repeat_event_count = 0

        self._last_event_info = info
        self._write_event(info)

    def _write_event(self, info: EventInfo, repeat_count: int = 0):
        output = f"{info.when or datetime.now()}, {info.index or time.perf_counter_ns()}, {info.kind}, {str(info.kind)}, {repeat_count}, {str(info.context)}"

        # TODO Roll on the hour
        if self._event_file is not None:
            self._event_file.write(f"{output}\n")

        logger.debug(f"<EventManager>: {output}")

    def _update_event_file(self):
        if self._event_file is not None:
            self._event_file.close()
            self._event_file = None

        if self._project_info is not None:
            event_file_info = self._project_info.get_monitor_file(name="events", interval=ProjectInterval.HOUR)

            if event_file_info is None:
                logger.error(f"<EventManager>: unable to write to expected event file location")
                return

            try:
                file_existed = os.path.exists(event_file_info.file)

                location = open(event_file_info.file, "a")

                if not file_existed:
                    location.write("Time, Index, EventId, EventName, Repeat, Data\n")

                self._event_file = location
                logger.info(f"<EventManager>: saving to {event_file_info.file}")
            except Exception as ex:
                logger.error(f"<EventManager>: unable to write to {event_file_info.file}")
                logger.error(ex)
