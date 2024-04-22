import os

from PySide6.QtCore import QCoreApplication, QSettings


class UserSettings:
    def __init__(self):
        QCoreApplication.setOrganizationName("Colorado")
        QCoreApplication.setOrganizationDomain("colorado.edu")
        QCoreApplication.setApplicationName("HeadFIxUI")

        self._settings = QSettings()

    def save(self):
        self._settings.sync()

    @property
    def port(self) -> str:
        return self._settings.value("port", "")

    @port.setter
    def port(self, value: str):
        self._settings.setValue("port", value)

    def set_port(self, value: str) -> None:
        self.port = value

    @property
    def record_enabled(self) -> bool:
        return self._settings.value("record_enabled", True, bool)

    @record_enabled.setter
    def record_enabled(self, value: bool) -> None:
        self._settings.setValue("record_enabled", value)

    @property
    def record_location(self) -> str:
        return self._settings.value("record_location", os.path.expanduser("~"))

    @record_location.setter
    def record_location(self, value: str) -> None:
        self._settings.setValue("record_location", value)
