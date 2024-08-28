import sys

from PySide6.QtCore import QCoreApplication, QSettings

from autotrainer.core import ObservableObject


class UserSettings(ObservableObject):
    def __init__(self):
        super().__init__()

        if sys.platform.startswith('win'):
            self._settings = QSettings(QSettings.IniFormat, QSettings.UserScope, "Colorado", "Auto Trainer")
        else:
            QCoreApplication.setOrganizationName("Colorado")
            QCoreApplication.setOrganizationDomain("colorado.edu")
            QCoreApplication.setApplicationName("Auto Trainer")
            self._settings = QSettings()

    def save(self):
        self._settings.sync()

    @property
    def last_window_x(self) -> int:
        return self._settings.value("system/last_window_x", 0, int)

    @last_window_x.setter
    def last_window_x(self, value: int):
        self._settings.setValue("system/last_window_x", value)

    @property
    def last_window_y(self) -> int:
        return self._settings.value("system/last_window_y", 0, int)

    @last_window_y.setter
    def last_window_y(self, value: int):
        self._settings.setValue("system/last_window_y", value)

    @property
    def last_configuration(self) -> str:
        return self._settings.value("system/last_configuration", "")

    @last_configuration.setter
    def last_configuration(self, value: str) -> None:
        value = self._on_property_changed("last_configuration", value, self.last_configuration)
        self._settings.setValue("system/last_configuration", value)

    @property
    def serial_number(self) -> str:
        return self._settings.value("system/serial_number", "00000")

    @serial_number.setter
    def serial_number(self, value: str):
        self._settings.setValue("system/serial_number", value)

    @property
    def live_feed_refresh_rate(self) -> int:
        return self._settings.value("display/refresh_rate", 15, int)

    @live_feed_refresh_rate.setter
    def live_feed_refresh_rate(self, value: int):
        self._settings.setValue("display/refresh_rate", value)
