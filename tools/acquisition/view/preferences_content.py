import logging

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QWidget, QFormLayout, QLineEdit, QComboBox, QLabel, QHBoxLayout, QPushButton, \
    QFileDialog, QTabWidget, QVBoxLayout

from autotrainer.device import get_available_hardware
from autotrainer.model import EnvironmentProvider, HardwareVersion
from autotrainer.pyside import ATSeparator, ATSerialPortComboBox
from tools.acquisition.model.user_preferences import UserPreferences


class PreferencesContent(QWidget):
    def __init__(self, preferences: UserPreferences, parent=None):
        super(PreferencesContent, self).__init__(parent)

        self._preferences = preferences

        self._tunnel_combo_box = None
        self._pellet_combo_box = None

        self._tabs = QTabWidget(self)

        self._general_tab = self._create_general_tab()
        self._tabs.addTab(self._general_tab, "General")

        # TODO: Still using controls in the panels of the main window.
        # self._hardware_tab = self._create_hardware_tab()
        # self._tabs.addTab(self._hardware_tab, "Hardware")

        # TODO: Still using controls in the panels of the main window.
        # self._behavior_tab = self._create_behavior_tab()
        # self._tabs.addTab(self._behavior_tab, "Behavior")

        self._advanced_tab = self._create_advanced_tab()
        self._tabs.addTab(self._advanced_tab, "Advanced")

        layout = QVBoxLayout()
        layout.addWidget(self._tabs)
        self.setLayout(layout)

    def _create_general_tab(self):
        self._device_id_edit = QLineEdit()
        self._device_id_edit.setText(self._preferences.serial_number)
        self._device_id_edit.textChanged.connect(self._device_id_changed)

        self._animal_location_edit = QLineEdit()
        self._animal_location_edit.setText(self._preferences.animal_location)
        self._animal_location_edit.textChanged.connect(self._animal_location_changed)

        form_layout = QFormLayout()

        form_layout.addRow("Device Id:", self._device_id_edit)

        layout = QHBoxLayout()
        layout.addWidget(self._animal_location_edit)
        button = QPushButton("Select...")
        button.clicked.connect(lambda: self._browse_for_location("animal"))
        layout.addWidget(button)

        form_layout.addRow("Animal location:", layout)

        tab = QWidget()
        tab.setLayout(form_layout)

        return tab

    def _create_hardware_tab(self):
        form_layout = QFormLayout()

        form_layout.addRow("Device:", QLabel(str(EnvironmentProvider.hardware_version())))

        if EnvironmentProvider.hardware_version() == HardwareVersion.ALOGUS_V1:
            layout = QVBoxLayout()
            layout.addLayout(form_layout)

            label = QLabel("There are no configurable options for this device.")
            font = QFont()
            font.setItalic(True)
            label.setFont(font)
            layout.addWidget(label)
        else:
            ports = get_available_hardware(allow_can_emulation=EnvironmentProvider.allow_can_emulation())

            self._tunnel_combo_box = ATSerialPortComboBox(ports, self._preferences.tunnel_port)
            form_layout.addRow("Tunnel Port:", self._tunnel_combo_box)
            self._pellet_combo_box = ATSerialPortComboBox(ports, self._preferences.pellet_port)
            form_layout.addRow("Pellet Port:", self._pellet_combo_box)

            layout = form_layout

        tab = QWidget()
        tab.setLayout(layout)

        return tab

    def _create_behavior_tab(self):
        form_layout = QFormLayout()

        tab = QWidget()
        tab.setLayout(form_layout)

        return tab

    def _create_advanced_tab(self):
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
        self._log_location_edit.setText(self._preferences.log_location)
        self._log_location_edit.textChanged.connect(self._log_location_changed)

        form_layout = QFormLayout()

        layout = QHBoxLayout()
        layout.addWidget(self._log_location_edit)
        button = QPushButton("Select...")
        button.clicked.connect(lambda: self._browse_for_location("log"))
        layout.addWidget(button)

        form_layout.addRow("Log location:", layout)

        form_layout.addRow("", QLabel("Log location change requires restart.  Leave blank for default location."))
        form_layout.addRow("Log level:", self._log_level_combobox)

        # May want these back with some future additions.
        # form_layout.addRow(QWidget())
        # form_layout.addRow(ATSeparator())
        # form_layout.addRow(QWidget())

        tab = QWidget()
        tab.setLayout(form_layout)

        return tab

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
