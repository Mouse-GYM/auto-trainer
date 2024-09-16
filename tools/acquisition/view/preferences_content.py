import logging

from PySide6.QtWidgets import QWidget, QFormLayout, QLineEdit, QComboBox

from tools.acquisition.model.user_preferences import UserPreferences


class PreferencesContent(QWidget):
    def __init__(self, preferences: UserPreferences, parent=None):
        super(PreferencesContent, self).__init__(parent)

        self._preferences = preferences

        self._device_id_edit = QLineEdit()
        self._device_id_edit.setText(preferences.serial_number)
        self._device_id_edit.textChanged.connect(self._device_id_changed)

        self._log_level_combobox = QComboBox()
        self._log_level_combobox.addItem("Warning", logging.WARNING)
        self._log_level_combobox.addItem("Info", logging.INFO)
        self._log_level_combobox.addItem("Debug", logging.DEBUG)
        self._log_level_combobox.currentIndexChanged.connect(self._log_level_changed)

        if self._preferences.log_level == logging.INFO:
            self._log_level_combobox.setCurrentIndex(1)
        elif self._preferences.log_level == logging.DEBUG:
            self._log_level_combobox.setCurrentIndex(2)
        else:
            self._log_level_combobox.setCurrentIndex(0)

        self.layout = QFormLayout()

        self.layout.addRow("Device Id:", self._device_id_edit)
        self.layout.addRow("Log level:", self._log_level_combobox)

        self.setLayout(self.layout)

    def _device_id_changed(self, value: str):
        self._preferences.serial_number = value

    def _log_level_changed(self, value):
        if value != -1:
            self._preferences.log_level = self._log_level_combobox.itemData(value)
