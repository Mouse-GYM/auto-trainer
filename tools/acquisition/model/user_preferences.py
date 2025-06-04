import logging
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QSettings

from autotrainer.core import ObservableObject


def _find_default_configuration_location() -> str:
    return str(Path.home().joinpath("Autotrainer"))


def _find_default_data_location() -> str:
    return str(Path.home().joinpath("Documents").joinpath("RawDataLocal"))


class UserPreferences(ObservableObject):
    def __init__(self):
        super().__init__()

        if sys.platform.startswith("win"):
            self._settings = QSettings(QSettings.IniFormat, QSettings.UserScope, "Colorado", "Auto Trainer")
        else:
            QCoreApplication.setOrganizationName("Colorado")
            QCoreApplication.setOrganizationDomain("colorado.edu")
            QCoreApplication.setApplicationName("Auto Trainer")
            self._settings = QSettings()

        self._serial_number = self._settings.value("system/serial_number", "00000")

        self._last_configuration = self._settings.value("system/last_configuration", "")

        self._configuration_location = self._settings.value("system/configuration_location",
                                                            _find_default_configuration_location())

        self._animal_location = self._settings.value("system/animal_location", "")

        self._log_location: str = self._settings.value("system/log_location", "")
        self._log_level = self._settings.value("system/log_level", logging.WARNING, int)

        self._live_feed_refresh_rate = self._settings.value("display/refresh_rate", 15, int)

        # Transient values that may come from individual configuration files, but are conveniently accessed from
        # the user preferences.

        self._tunnel_port = None
        self._pellet_port = None

    def save(self):
        self._settings.sync()

    @property
    def last_configuration(self) -> str:
        return self._last_configuration

    @property
    def configuration_location(self) -> str:
        return self._configuration_location

    @configuration_location.setter
    def configuration_location(self, value: str) -> None:
        self._configuration_location = self._on_property_changed("configuration_location", value,
                                                                 self._configuration_location)
        self._settings.setValue("system/configuration_location", self._configuration_location)

    @property
    def serial_number(self) -> str:
        return self._serial_number

    @serial_number.setter
    def serial_number(self, value: str):
        self._serial_number = self._on_property_changed("serial_number", value, self.serial_number)
        self._settings.setValue("system/serial_number", self._serial_number)

    @property
    def live_feed_refresh_rate(self) -> int:
        return self._live_feed_refresh_rate

    @live_feed_refresh_rate.setter
    def live_feed_refresh_rate(self, value: int):
        self._live_feed_refresh_rate = self._on_property_changed("live_feed_refresh_rate", value,
                                                                 self.live_feed_refresh_rate)
        self._settings.setValue("display/refresh_rate", self._live_feed_refresh_rate)

    @property
    def log_location(self) -> str:
        return self._log_location

    @log_location.setter
    def log_location(self, value: str) -> None:
        self._log_location = self._on_property_changed("log_location", value, self.log_location)
        self._settings.setValue("system/log_location", self._log_location)

    @property
    def animal_location(self) -> str:
        return self._animal_location

    @animal_location.setter
    def animal_location(self, value: str) -> None:
        self._animal_location = self._on_property_changed("animal_location", value, self.animal_location)
        self._settings.setValue("system/animal_location", self._animal_location)

    @property
    def log_level(self) -> int:
        return self._log_level

    @log_level.setter
    def log_level(self, value: int):
        self._log_level = self._on_property_changed("log_level", value, self.log_level)
        self._settings.setValue("system/log_level", self._log_level)

    # Transient Values

    @property
    def pellet_port(self) -> str:
        return self._pellet_port

    @pellet_port.setter
    def pellet_port(self, value: str):
        self._pellet_port = self._on_property_changed("pellet_port", value, self.pellet_port)

    @property
    def tunnel_port(self) -> str:
        return self._tunnel_port

    @tunnel_port.setter
    def tunnel_port(self, value: str):
        self._tunnel_port = self._on_property_changed("tunnel_port", value, self.tunnel_port)
