import importlib.util

from .event_info import EventInfo
from .event_manager import EventManager
from .event_manager_plugin import EventManagerPlugin
from ..logging import get_verbose_logger

logger = get_verbose_logger(__name__)

_spec_api = importlib.util.find_spec("autotrainer.api")


def try_register_api_event_plugin() -> bool:
    """
    Attempt to register the Autotrainer External API plugin with the default instance of the event manager.

    Returns:
        bool: True if the plugin was successfully registered, False otherwise.
    """
    if _spec_api is not None:
        try:
            from autotrainer.core.event.api_event_plugin import ApiEventPlugin
            from autotrainer.api import create_default_api_options
            plugin = ApiEventPlugin(create_default_api_options())
            plugin.set_enable(True)
            EventManager.default().register_plugin(plugin)
            return True
        except Exception as ex:
            logger.error(f"API plugin module available, however registration failed: {ex}")

    return False
