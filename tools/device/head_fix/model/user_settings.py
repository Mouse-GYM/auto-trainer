from PySide6.QtCore import QCoreApplication, QSettings


class UserSettings:
    def __init__(self):
        QCoreApplication.setOrganizationName("Colorado")
        QCoreApplication.setOrganizationDomain("colorado.edu")
        QCoreApplication.setApplicationName("HeadFIxUI")

        self._settings = QSettings()

        self._cameras = None

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
