
from typing import Optional

from autotrainer.api.api_event_kind import ApiEventKind
from autotrainer.api import create_default_api_options

from autotrainer.core.event.api_event_plugin import ApiEventPlugin
from autotrainer.core.event.api_event_plugin import ApiEventPlugin

from .event_info import EventInfo
from .event_manager import EventManager
from .event_manager_plugin import EventManagerPlugin
from ..logging import get_verbose_logger

logger = get_verbose_logger(__name__)


__all__ = [
    "ApiEventKind",
    "try_register_api_event_plugin",
]


def try_register_api_event_plugin() -> Optional[ApiEventPlugin]:
    """
    Attempt to register the Autotrainer External API plugin with the default instance of the event manager.

    Returns:
        bool: True if the plugin was successfully registered, False otherwise.
    """
    try:
        # NB: keeping import here,
        # given otherwise it gives app crash at start if it's imported before the main qt app instance is created

        plugin = ApiEventPlugin(create_default_api_options())
        plugin.set_enable(True)
        EventManager.default().register_plugin(plugin)
        return plugin
    except Exception as err:
        logger.exception("API plugin creation or registration failed: %s", err)

    return None

def post_api_detector_event_content(event_manager: EventManager, detector_id, active, enabled):
    event_manager.post_event_content(ApiEventKind.detectorChanged, context={
        "detector_id": detector_id,
        "is_active": active,
        "is_enabled": enabled,
    })
