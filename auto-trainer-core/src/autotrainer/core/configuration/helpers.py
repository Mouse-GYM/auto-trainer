
from pathlib import Path
from typing import Optional

from autotrainer.core import get_verbose_logger
from autotrainer.core.configuration import SystemConfiguration
from autotrainer.core.user_preferences import get_default_configuration_location, UserPreferences

logger = get_verbose_logger(__name__)


def get_config_location(preferences: UserPreferences, location: Optional[str] = None) -> Path:
    if location is None:
        # Check to see if there is a file in the new default location.  If so, use it.
        path = Path(preferences.configuration_location)
        logger.info(
            "did not receive explicit configuration file, trying default p_location=%s",
            location,
        )
        default_path = SystemConfiguration.make_default_yaml_config_path(path)
        if default_path.is_file():
            return default_path
        file_path = Path(preferences.last_configuration)
        if file_path.is_file():
            return file_path
        default_path = SystemConfiguration.make_default_yaml_config_path(
            get_default_configuration_location()
        )
        return default_path
    path = Path(location)
    if path.is_dir():
        return SystemConfiguration.make_default_yaml_config_path(path)
    return path
