import sys
import os
from pathlib import Path
from datetime import datetime
from dateutil import parser

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
    def serial_number(self) -> str:
        return self._settings.value("system/serial_number", "00000")

    @serial_number.setter
    def serial_number(self, value: str):
        self._settings.setValue("system/serial_number", value)

    @property
    def session_date(self) -> str:
        return self._settings.value("system/session_date", "")

    @session_date.setter
    def session_date(self, value: str):
        self._settings.setValue("system/session_date", value)

    @property
    def session_index(self) -> int:
        return self._settings.value("system/session_index", 0, int)

    @session_index.setter
    def session_index(self, value: int):
        self._settings.setValue("system/session_index", value)

    @property
    def live_feed_refresh_rate(self) -> int:
        return self._settings.value("display/refresh_rate", 15, int)

    @live_feed_refresh_rate.setter
    def live_feed_refresh_rate(self, value: int):
        self._settings.setValue("display/refresh_rate", value)

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
        return self._settings.value("head_fix/trigger", 15, int)

    @head_trigger.setter
    def head_trigger(self, value: int):
        self._settings.setValue("head_fix/trigger", value)

    @property
    def pellet_port(self) -> str:
        return self._settings.value("pellet_delivery/port", "")

    @pellet_port.setter
    def pellet_port(self, value: str):
        self._settings.setValue("pellet_delivery/port", value)

    @property
    def analysis_enabled(self) -> bool:
        return self._settings.value("analysis/enabled", False, bool)

    @analysis_enabled.setter
    def analysis_enabled(self, value: bool):
        self._settings.setValue("analysis/enabled", value)

    @property
    def analysis_model(self) -> str:
        return self._settings.value("analysis/model", "")

    @analysis_model.setter
    def analysis_model(self, value: str):
        self._settings.setValue("analysis/model", value)

    @property
    def analysis_algorithm(self) -> str:
        return self._settings.value("analysis/algorithm", "")

    @analysis_algorithm.setter
    def analysis_algorithm(self, value: str):
        self._settings.setValue("analysis/algorithm", value)

    def get_next_session_path(self) -> (str, int):
        file_timestamp = datetime.now()
        session_index = 1
        try:
            last = parser.parse(self.session_date)
            if last is not None and last.year == file_timestamp.year and last.month == file_timestamp.month and last.day == file_timestamp.day:
                session_index = self.session_index
            else:
                self.session_date = file_timestamp.strftime("%Y%m%d")
                self.session_index = 0
        except:
            self.session_date = file_timestamp.strftime("%Y%m%d")
            self.session_index = 0

        prefix = os.path.join(self.output_location, file_timestamp.strftime("%Y%m%d"),
                              self.serial_number, f"session{session_index:03}")
        path = Path(prefix)
        path.mkdir(parents=True, exist_ok=True)

        location = os.path.join(prefix,
                                f"{file_timestamp.strftime('%Y%m%d')}_{self.serial_number}_session{session_index:03}")

        return location, session_index
