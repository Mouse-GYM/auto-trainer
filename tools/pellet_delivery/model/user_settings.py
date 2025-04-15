from PySide6.QtCore import QCoreApplication, QSettings

from autotrainer.device import CAN_IDENTIFIER


class UserSettings:
    def __init__(self):
        QCoreApplication.setOrganizationName("Colorado")
        QCoreApplication.setOrganizationDomain("colorado.edu")
        QCoreApplication.setApplicationName("PelletDeliveryUI")

        self._settings = QSettings()

        self._cameras = None

    def save(self):
        self._settings.sync()

    @property
    def port(self) -> str:
        p = self._settings.value("port", "")
        if p.find(CAN_IDENTIFIER) >= 0:
            p = CAN_IDENTIFIER

        return p

    @port.setter
    def port(self, value: str):
        self._settings.setValue("port", value)

    def set_port(self, value: str) -> None:
        self.port = value
