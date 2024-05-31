import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget, QGridLayout, QComboBox, QHBoxLayout, QPushButton, QLabel, QVBoxLayout, QSpinBox, \
    QPlainTextEdit

import qtawesome as qta

from autotrainer.pyside import TextBoxHandler
from tools.device.pellet_delivery.view.pellet_control import PelletControl


class MainContent(QWidget):
    connecting = Signal()
    disconnected = Signal()

    def __init__(self, app_view_model):
        super().__init__()

        self._app_view_model = app_view_model

        self._ignore_port_changes = False

        layout = QGridLayout()

        layout.setContentsMargins(0, 0, 0, 0)

        port_layout = QHBoxLayout()

        port_layout.setContentsMargins(8, 8, 8, 8)

        port_layout.setSpacing(8)

        port_layout.addWidget(QLabel("Port:"))

        self._port_combobox = QComboBox()

        self._refresh_ports()

        self._port_combobox.currentIndexChanged.connect(self._port_selection_changed)

        port_layout.addWidget(self._port_combobox, 0)

        self._refresh_button = QPushButton("")
        self._refresh_button.setIcon(QIcon(qta.icon('fa5s.redo')))
        self._refresh_button.clicked.connect(self._refresh_ports())

        port_layout.addWidget(self._refresh_button, 0)

        port_layout.addWidget(QWidget(), 1)

        self._connect_button = QPushButton("Connect")
        self._connect_button.clicked.connect(self._connect)
        port_layout.addWidget(self._connect_button, 0, Qt.AlignRight)

        layout.addLayout(port_layout, 0, 0)

        self._pellet_control = PelletControl(self._app_view_model)
        layout.addWidget(self._pellet_control, 1, 0)

        log_output = QPlainTextEdit()
        log_output.setReadOnly(True)
        layout.addWidget(log_output, 2, 0)
        handler = TextBoxHandler(log_output)
        handler.setFormatter(logging.Formatter(fmt="%(asctime)s: %(levelname)s: %(name)s: %(message)s"))
        logging.getLogger("autotrainer").addHandler(handler)

        layout.setContentsMargins(8, 8, 8, 8)

        layout.setRowStretch(2, 1)

        self.setLayout(layout)

    def on_activated(self):
        pass

    def _refresh_ports(self):
        self._app_view_model.refresh_ports()

        match = -1

        self._ignore_port_changes = True

        self._port_combobox.clear()

        for idx, port in enumerate(self._app_view_model.ports):
            self._port_combobox.addItem(port)
            if port == self._app_view_model.user_settings.port:
                match = idx

        self._port_combobox.setCurrentIndex(match)

        self._ignore_port_changes = False

    def _port_selection_changed(self, index: int):
        if not self._ignore_port_changes and len(self._port_combobox.currentText()) > 0:
            self._app_view_model.user_settings.set_port(self._port_combobox.currentText())

    def _update_position(self):
        self._app_view_model.update_position(self._position.value())

    def _connect(self):
        if self._app_view_model.is_connected:
            self._app_view_model.disconnect_from_device()
            self._connect_button.setText("Connect")
            self.disconnected.emit()
        else:
            self.connecting.emit()
            self._app_view_model.connect_to_device()
            self._connect_button.setText("Disconnect")

        self._pellet_control.setEnabled(self._app_view_model.is_connected)
        self._port_combobox.setEnabled(not self._app_view_model.is_connected)
        self._refresh_button.setEnabled(not self._app_view_model.is_connected)
