import sys

from PySide6.QtCore import QCoreApplication, QSettings

from autotrainer.core import ObservableObject


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

        self._last_configuration = self._settings.value("system/last_configuration", "")
        self._log_location: str = self._settings.value("system/log_location", "")
        self._log_level = self._settings.value("system/log_level", 30, int)
        self._serial_number = self._settings.value("system/serial_number", "00000")
        self._live_feed_refresh_rate = self._settings.value("display/refresh_rate", 15, int)

        self._animal_location = self._settings.value("system/animal_location", "")

    def save(self):
        self._settings.sync()

    @property
    def last_configuration(self) -> str:
        return self._last_configuration

    @last_configuration.setter
    def last_configuration(self, value: str) -> None:
        self._last_configuration = self._on_property_changed("last_configuration", value, self.last_configuration)
        self._settings.setValue("system/last_configuration", self._last_configuration)

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
