import logging

from PySide6 import QtCore
from PySide6.QtWidgets import QWidget, QFormLayout, QLineEdit, QComboBox, QLabel, QHBoxLayout, QPushButton, QFileDialog, \
    QFrame

from autotrainer.pyside import ATSeparator
from tools.acquisition.model.user_preferences import UserPreferences


class PreferencesContent(QWidget):
    def __init__(self, preferences: UserPreferences, parent=None):
        super(PreferencesContent, self).__init__(parent)

        self._preferences = preferences

        self._device_id_edit = QLineEdit()
        self._device_id_edit.setText(preferences.serial_number)
        self._device_id_edit.textChanged.connect(self._device_id_changed)

        self._animal_location_edit = QLineEdit()
        self._animal_location_edit.setText(preferences.animal_location)
        self._animal_location_edit.textChanged.connect(self._animal_location_changed)

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

        self._log_location_edit = QLineEdit()
        self._log_location_edit.setText(preferences.log_location)
        self._log_location_edit.textChanged.connect(self._log_location_changed)

        self.layout = QFormLayout()

        self.layout.addRow("Device Id:", self._device_id_edit)

        layout = QHBoxLayout()
        layout.addWidget(self._animal_location_edit)
        button = QPushButton("Select...")
        button.clicked.connect(lambda: self._browse_for_location("animal"))
        layout.addWidget(button)

        self.layout.addRow("Animal location:", layout)

        self.layout.addRow(QWidget())
        self.layout.addRow(ATSeparator())
        self.layout.addRow(QWidget())

        layout = QHBoxLayout()
        layout.addWidget(self._log_location_edit)
        button = QPushButton("Select...")
        button.clicked.connect(lambda: self._browse_for_location("log"))
        layout.addWidget(button)

        self.layout.addRow("Log location:", layout)

        self.layout.addRow("", QLabel("Log location change requires restart.  Leave blank for default location."))
        self.layout.addRow("Log level:", self._log_level_combobox)

        self.setLayout(self.layout)

    def _device_id_changed(self, value: str):
        self._preferences.serial_number = value

    def _animal_location_changed(self, value: str):
        self._preferences.animal_location = value

    def _log_level_changed(self, value):
        if value != -1:
            self._preferences.log_level = self._log_level_combobox.itemData(value)

    def _log_location_changed(self, value: str):
        self._preferences.log_location = value

    def _browse_for_location(self, which: str):
        if which == "animal":
            initial_location = self._preferences.animal_location
        else:
            initial_location = self._preferences.log_location

        dirname = QFileDialog.getExistingDirectory(self, "Select Directory", initial_location)

        if len(dirname) > 0:
            if which == "animal":
                self._animal_location_edit.setText(dirname)
            else:
                self._log_location_edit.setText(dirname)
