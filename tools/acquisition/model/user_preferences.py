import logging
import sys
from pathlib import Path
from typing import Optional, Union

from PySide6.QtCore import QCoreApplication, QSettings

from autotrainer.core import ObservableObject
from autotrainer.core.logging import get_verbose_logger

logger = get_verbose_logger(__name__)


def _find_default_configuration_location() -> str:
    return str(Path.home().joinpath("Autotrainer"))


def _find_default_data_location() -> str:
    return str(Path.home().joinpath("Documents").joinpath("RawDataLocal"))


class UserPreferences(ObservableObject):

    CONFIGURATION_LOCATION = "configuration_location"
    SERIAL_NUMBER = "serial_number"
    LIVE_FEED_REFRESH_RATE = "live_feed_refresh_rate"
    LOG_LOCATION = "log_location"
    LOG_LEVEL = "log_level"
    SELECTED_ANIMAL = "selected_animal"
    ANIMAL_LOCATION = "animal_location"
    PELLET_PORT = "pellet_port"
    TUNNEL_PORT = "tunnel_port"
    REMOVE_RAW_DATA_WHEN_INACTIVE_SESSION = "remove_raw_data_when_inactive_session"
    MEASUREMENT_GRAPH = "measurement_graph"

    def __init__(self, *, settings_file_path: Optional[Path] = None):
        super().__init__()

        settings_args = [] if settings_file_path is None else [settings_file_path.as_posix()]
        if sys.platform.startswith("win"):
            settings_args.extend((QSettings.IniFormat, QSettings.UserScope, "Colorado", "Auto Trainer"))
            settings = self._settings = QSettings(*settings_args)
        else:
            QCoreApplication.setOrganizationName("Colorado")
            QCoreApplication.setOrganizationDomain("colorado.edu")
            QCoreApplication.setApplicationName("Auto Trainer")
            settings = self._settings = QSettings(*settings_args)

        logger.verbose("Using setting ini file: %r", settings.fileName())

        self._serial_number = settings.value("system/serial_number", "00000")

        self._last_configuration = settings.value("system/last_configuration", "")

        self._configuration_location = settings.value("system/configuration_location",
                                                      _find_default_configuration_location())

        self._animal_location = settings.value("system/animal_location", "")
        self._selected_animal = settings.value("system/selected_animal", "")

        self._log_location: str = settings.value("system/log_location", "")
        self._log_level = settings.value("system/log_level", logging.WARNING, int)

        self._live_feed_refresh_rate = settings.value("display/refresh_rate", 15, int)

        self._measurement_graph = settings.value("ui/measurement_graph", "")

        # Transient values that may come from individual configuration files, but are conveniently accessed from
        # the user preferences.

        self._tunnel_port = None
        self._pellet_port = None

        self._remove_raw_data_when_inactive_session: bool = False

    def save(self):
        logger.verbose("Saving ini config to %s", self._settings.fileName())
        self._settings.sync()

    @property
    def last_configuration(self) -> str:
        return self._last_configuration

    @property
    def configuration_location(self) -> str:
        return self._configuration_location

    @configuration_location.setter
    def configuration_location(self, value: Union[str, Path]) -> None:
        value = Path(value).as_posix()
        prev, self._configuration_location = self._configuration_location, value
        self._on_property_changed(self.CONFIGURATION_LOCATION, value, prev)
        self._settings.setValue("system/configuration_location", value)

    @property
    def serial_number(self) -> str:
        return self._serial_number

    @serial_number.setter
    def serial_number(self, value: str):
        self._serial_number = self._on_property_changed(self.SERIAL_NUMBER, value, self.serial_number)
        self._settings.setValue("system/serial_number", self._serial_number)

    @property
    def live_feed_refresh_rate(self) -> int:
        return self._live_feed_refresh_rate

    @live_feed_refresh_rate.setter
    def live_feed_refresh_rate(self, value: int):
        self._live_feed_refresh_rate = self._on_property_changed(self.LIVE_FEED_REFRESH_RATE, value,
                                                                 self.live_feed_refresh_rate)
        self._settings.setValue("display/refresh_rate", self._live_feed_refresh_rate)

    @property
    def log_location(self) -> str:
        return self._log_location

    @log_location.setter
    def log_location(self, value: Union[str, Path]):
        value = Path(value).as_posix()
        prev, self._log_location = self._log_location, value
        self._on_property_changed(self.LOG_LOCATION, value, prev)
        self._settings.setValue("system/log_location", value)

    @property
    def selected_animal(self) -> str:
        return self._selected_animal

    @selected_animal.setter
    def selected_animal(self, value: str):
        # set new value first,
        prev, self._selected_animal = self._selected_animal, value
        # then eventually trigger the on_property_changed event:
        self._on_property_changed(self.SELECTED_ANIMAL, value, prev)
        self._settings.setValue("system/selected_animal", value)

    @property
    def animal_location(self) -> str:
        return self._animal_location

    @animal_location.setter
    def animal_location(self, value: Union[str, Path]):
        value = Path(value).as_posix()
        prev, self._animal_location = self._animal_location, value
        self._on_property_changed(self.ANIMAL_LOCATION, value, prev)
        self._settings.setValue("system/animal_location", value)

    @property
    def log_level(self) -> int:
        return self._log_level

    @log_level.setter
    def log_level(self, value: int):
        self._log_level = self._on_property_changed(self.LOG_LEVEL, value, self.log_level)
        self._settings.setValue("system/log_level", self._log_level)

    # Transient Values

    @property
    def pellet_port(self) -> str:
        return self._pellet_port

    @pellet_port.setter
    def pellet_port(self, value: str):
        self._pellet_port = self._on_property_changed(self.PELLET_PORT, value, self.pellet_port)

    @property
    def tunnel_port(self) -> str:
        return self._tunnel_port

    @tunnel_port.setter
    def tunnel_port(self, value: str):
        self._tunnel_port = self._on_property_changed(self.TUNNEL_PORT, value, self.tunnel_port)

    @property
    def remove_raw_data_when_inactive_session(self) -> bool:
        return self._remove_raw_data_when_inactive_session

    @remove_raw_data_when_inactive_session.setter
    def remove_raw_data_when_inactive_session(self, value):
        self._remove_raw_data_when_inactive_session = self._on_property_changed(
            self.REMOVE_RAW_DATA_WHEN_INACTIVE_SESSION, value, self._remove_raw_data_when_inactive_session)

    @property
    def measurement_graph(self) -> str:
        return self._measurement_graph

    @measurement_graph.setter
    def measurement_graph(self, value: str) -> None:
        self._measurement_graph = self._on_property_changed(self.MEASUREMENT_GRAPH, value, self._measurement_graph)
        self._settings.setValue("ui/measurement_graph", value)
