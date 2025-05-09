from datetime import datetime
from pathlib import Path
from typing import Optional

from ..logging import get_verbose_logger
from ..project import ProjectInfo, ProjectInterval
from .event_info import EventInfo

from .event_manager_plugin import EventManagerPlugin

logger = get_verbose_logger(__name__)


class FileEventPlugin(EventManagerPlugin):
    """
    An event manager plugin directs events to a project file.  This plugin will nore record an event history if
    `project` is set to `None`.
    """

    def __init__(self):
        self._project_info = None
        self._event_file = None
        self._write_active = True
        self._current_record_interval = -1
        self._bad_file_attempt = False

    def set_project(self, project: Optional[ProjectInfo]) -> None:
        self._project_info = project
        self._bad_file_attempt = False
        self._update_event_file()

    def set_enable(self, enable: bool) -> None:
        self._write_active = enable

    def process_event(self, info: EventInfo, repeat_count: int) -> None:
        if self._event_file is not None:
            output = f"{info.when}, {info.index}, {info.kind}, {str(info.kind)}, {str(info.context)}, {repeat_count}\n"

            file_timestamp = datetime.now()

            needs_update = file_timestamp.hour != self._current_record_interval

            if needs_update:
                self._update_event_file()

            self._event_file.write(output)

    def flush(self):
        if self._event_file is not None:
            self._event_file.flush()

    def close(self) -> None:
        if self._event_file is not None:
            self._event_file.close()
            self._event_file = None

    def _update_event_file(self):
        self.close()

        if not self._write_active:
            return

        if self._project_info is not None:
            event_file_info = self._project_info.get_monitor_file(name="events", interval=ProjectInterval.HOUR)

            if event_file_info is None:
                logger.error(f"unable to write to expected event file location")
                return

            try:
                file_existed = Path(event_file_info.file).exists()

                location = open(event_file_info.file, "a")

                if not file_existed:
                    location.write("Time, Index, EventId, EventName, Data, Repeat\n")

                self._current_record_interval = event_file_info.current_interval
                self._event_file = location

                logger.info(f"event file opened at {event_file_info.file}")
            except Exception as ex:
                if not self._bad_file_attempt:
                    # Don't spam log if there are write/access issues with wherever project info is pointing.  Can reset
                    # the flag the next tile the project changes.
                    logger.error(f"unable to write to {event_file_info.file}")
                    logger.error(ex)
                    self._bad_file_attempt = True
