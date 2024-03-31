from PySide6.QtWidgets import QGridLayout, QLabel, QLineEdit

from tools.acquisition.model.user_settings import UserSettings


class OutputContent(QGridLayout):

    def __init__(self, user_settings: UserSettings = None):
        super().__init__()

        self._user_settings = user_settings

        self.setContentsMargins(10, 10, 10, 10)

        self.setColumnStretch(1, 1)

        self.addWidget(QLabel("Output Location:"), 0, 0)

        location = QLineEdit()
        location.setText(self._user_settings.output_location)
        location.textChanged.connect(self.location_changed)
        self.addWidget(location, 0, 1)

    def location_changed(self, value: str):
        if self._user_settings is not None and value:
            self._user_settings.output_location = value
