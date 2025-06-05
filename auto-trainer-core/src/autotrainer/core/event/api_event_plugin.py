from dataclasses import asdict
from typing import Optional

from autotrainer.api import ApiOptions, RpcService, create_api_service, ApiTopic

from ..logging import get_verbose_logger
from ..project import ProjectInfo
from .event_info import EventInfo

from .event_manager_plugin import EventManagerPlugin

logger = get_verbose_logger(__name__)


class ApiEventPlugin(EventManagerPlugin):
    """
    An EventManager plugin that sends events to the auto-trainer-api facilities.

    This plugin requires the auto-trainer-api package to be installed.

    See auto-trainer-api for additional details.
    """

    def __init__(self, options: ApiOptions):
        self._options = options
        self._service: Optional[RpcService] = None

    def set_project(self, project: Optional[ProjectInfo]) -> None:
        pass

    def set_enable(self, enable: bool) -> None:
        if enable and self._service is None:
            self._service = create_api_service(self._options)
            self._service.start()
        elif not enable and self._service is not None:
            self._service.stop()
            self._service = None

    def process_event(self, info: EventInfo, repeat_count: int) -> None:
        if self._service is not None:
            self._service.send_dict(ApiTopic.EVENT, asdict(info))

    def flush(self) -> None:
        pass

    def close(self) -> None:
        if self._service is not None:
            self._service.stop()
            self._service = None
