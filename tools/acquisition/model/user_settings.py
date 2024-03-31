import sys

from PySide6.QtCore import QCoreApplication, QSettings


class UserSettings:
    def __init__(self):
        if sys.platform.startswith('win'):
            self._settings = QSettings(QSettings.IniFormat, QSettings.UserScope, "Colorado", "Auto Trainer")
        else:
            QCoreApplication.setOrganizationName("Colorado")
            QCoreApplication.setOrganizationDomain("colorado.edu")
            QCoreApplication.setApplicationName("Auto Trainer")
            self._settings = QSettings()

        self._cameras = None

    def save(self):
        self._settings.sync()

    @property
    def output_location(self) -> str:
        return self._settings.value("output/location", "")

    @output_location.setter
    def output_location(self, value: str):
        self._settings.setValue("output/location", value)

    @property
    def head_port(self) -> str:
        return self._settings.value("head_fix/port", "")

    @head_port.setter
    def head_port(self, value: str):
        self._settings.setValue("head_fix/port", value)

    @property
    def head_trigger(self) -> int:
        return self._settings.value("head_fix/trigger", 5000, int)

    @head_trigger.setter
    def head_trigger(self, value: int):
        self._settings.setValue("head_fix/trigger", value)

    @property
    def pellet_port(self) -> str:
        return self._settings.value("pellet_delivery/port", "")

    @pellet_port.setter
    def pellet_port(self, value: str):
        self._settings.setValue("pellet_delivery/port", value)

