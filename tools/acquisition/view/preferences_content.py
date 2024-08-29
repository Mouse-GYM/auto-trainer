from PySide6.QtWidgets import QWidget, QFormLayout, QLineEdit

from tools.acquisition.model.user_settings import UserSettings


class PreferencesContent(QWidget):
    def __init__(self, preferences: UserSettings, parent=None):
        super(PreferencesContent, self).__init__(parent)

        self._preferences = preferences

        self._device_id_edit = QLineEdit()
        self._device_id_edit.setText(preferences.serial_number)
        self._device_id_edit.textChanged.connect(self._device_id_changed)

        self.layout = QFormLayout()
        self.layout.addRow("Device Id:", self._device_id_edit)
        self.setLayout(self.layout)

    def _device_id_changed(self, value: str):
        self._preferences.serial_number = value
