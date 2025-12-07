
from typing import Optional

from .api_event_kind import ApiEventKind
from .event_info import EventInfo
from .event_manager import EventManager
from .event_manager_plugin import EventManagerPlugin
from ..logging import get_verbose_logger

logger = get_verbose_logger(__name__)



def try_register_api_event_plugin() -> Optional["ApiEventPlugin"]:
    """
    Attempt to register the Autotrainer External API plugin with the default instance of the event manager.

    Returns:
        bool: True if the plugin was successfully registered, False otherwise.
    """
    try:
        # NB: keeping import here,
        # given otherwise it gives app crash at start if it's imported before the main qt app instance is created
        from autotrainer.core.event.api_event_plugin import ApiEventPlugin
        from autotrainer.api import create_default_api_options

        plugin = ApiEventPlugin(create_default_api_options())
        plugin.set_enable(True)
        EventManager.default().register_plugin(plugin)
        return plugin
    except Exception as err:
        logger.exception("API plugin creation or registration failed: %s", err)

    return None
