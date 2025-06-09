from typing import Optional

from ..logging import get_verbose_logger
from ..project import ProjectInfo
from .event_info import EventInfo

from .event_manager_plugin import EventManagerPlugin

logger = get_verbose_logger(__name__)


class ApiEventPlugin(EventManagerPlugin):
    """
    An EventManager plugin that sends events to the auto-trainer-api facilities.  See auto-trainer-api for details.
    """

    def __init__(self):
        pass

    def set_project(self, project: Optional[ProjectInfo]) -> None:
        pass

    def set_enable(self, enable: bool) -> None:
        pass

    def process_event(self, info: EventInfo, repeat_count: int) -> None:
        pass

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass
