from __future__ import annotations

import logging
import os
import time
from threading import Thread
from dataclasses import dataclass
from datetime import datetime
from queue import Queue, Empty
from typing import Optional

from autotrainer.core import ProjectInfo, ProjectInterval


@dataclass(frozen=True)
class EventInfo:
    kind: int
    when: datetime = None
    index: int = None
    context: object = None

    def is_same(self, info: EventInfo) -> bool:
        return info is not None and self.kind == info.kind and self.context == info.context


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
        self._current_record_interval = -1
        self._last_event_info: Optional[EventInfo] = None
        self._repeat_event_count = 0

        self._write_active = True
        self._write_queue = Queue()
        self._write_thread = Thread(target=self._write_loop)
        self._write_thread.start()

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

    def close(self):
        self._write_active = False

    def post_event_info(self, info: EventInfo):
        self._write_queue.put(info)

    def post_event(self, kind: int, context: Optional[object] = None, when: Optional[datetime] = None,
                   index: int = None):
        info = EventInfo(kind, when=when or datetime.now(), index=index or time.perf_counter_ns(), context=context)

        self.post_event_info(info)

    def _write_loop(self):
        while self._write_active:
            try:
                info = self._write_queue.get_nowait()

                if not isinstance(info, EventInfo):
                    logger.debug(f"unexpected event type")
                    continue

                if info.is_same(self._last_event_info):
                    self._repeat_event_count += 1
                    continue

                if self._repeat_event_count > 0:
                    self._write_event(self._last_event_info, self._repeat_event_count)
                    self._repeat_event_count = 0

                self._last_event_info = info
                self._write_event(info)
            except Empty:
                time.sleep(0.05)
            except Exception as e:
                pass

    def _write_event(self, info: EventInfo, repeat_count: int = 0):
        output = f"{info.when}, {info.index}, {info.kind}, {str(info.kind)}, {str(info.context)}, {repeat_count}"

        if self._event_file is not None:
            file_timestamp = datetime.now()

            needs_update = file_timestamp.hour != self._current_record_interval

            if needs_update:
                self._update_event_file()

            self._event_file.write(f"{output}\n")

        logger.debug(output)

    def _update_event_file(self):
        if self._event_file is not None:
            self._event_file.close()
            self._event_file = None

        if self._project_info is not None:
            event_file_info = self._project_info.get_monitor_file(name="events", interval=ProjectInterval.HOUR)

            if event_file_info is None:
                logger.error(f"unable to write to expected event file location")
                return

            try:
                file_existed = os.path.exists(event_file_info.file)

                location = open(event_file_info.file, "a")

                if not file_existed:
                    location.write("Time, Index, EventId, EventName, Data, Repeat\n")

                self._current_record_interval = event_file_info.current_interval
                self._event_file = location
                logger.info(f"saving to {event_file_info.file}")
            except Exception as ex:
                logger.error(f"unable to write to {event_file_info.file}")
                logger.error(ex)
