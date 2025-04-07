import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget, QGridLayout, QHBoxLayout, QPushButton, QLabel, QPlainTextEdit, QVBoxLayout

import qtawesome as qta

from autotrainer.pyside import TextBoxHandler, ATSerialPortComboBox, CardWidget
from tools.pellet_delivery.model.app_model import AppModel
from tools.pellet_delivery.view.pellet_control import PelletControl
from tools.pellet_delivery.view.pellet_status import PelletStatus


class MainContent(QWidget):
    connecting = Signal()
    disconnected = Signal()

    def __init__(self, app_view_model: AppModel):
        super().__init__()

        self._app_view_model = app_view_model

        self._app_view_model.property_changed += self._model_property_changed

        self._ignore_port_changes = False

        self._is_diagnostics_visible = True

        layout = QVBoxLayout()

        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(self._create_connection_panel())

        self._pellet_control = PelletControl(self._app_view_model)
        layout.addWidget(self._pellet_control, )

        self._pellet_status = PelletStatus(self._app_view_model)
        layout.addWidget(self._pellet_status)

        log_output = QPlainTextEdit()
        log_output.setReadOnly(True)
        log_output.setStyleSheet("border: none")

        panel = CardWidget(header_background_color="#00b6de")
        panel.setContentWidget(log_output)

        header = QWidget()
        h_layout = QHBoxLayout()
        h_layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("Logs")
        title.setStyleSheet("font-weight: bold; color: white")
        h_layout.addWidget(title)

        h_layout.addStretch(1)

        header.setLayout(h_layout)
        panel.header.setContent(header)

        self._diagnostics_panel = panel

        layout.addWidget(self._diagnostics_panel)

        handler = TextBoxHandler(log_output)
        handler.setFormatter(logging.Formatter(fmt="%(asctime)s: %(levelname)s: %(name)s: %(message)s"))
        logging.getLogger("autotrainer").addHandler(handler)

        layout.setContentsMargins(8, 8, 8, 8)

        layout.setStretch(3, 1)

        self._layout = layout

        self.setLayout(layout)

        self._refresh_ports()

    @property
    def is_diagnostics_visible(self) -> bool:
        return self._is_diagnostics_visible

    def on_activated(self):
        pass

    def _refresh_ports(self):
        ports = self._app_view_model.refresh_ports()

        self._port_combobox.refresh_ports(ports)

    def set_diagnostics_visible(self, is_visible: bool):
        self._diagnostics_panel.setVisible(is_visible)
        self._is_diagnostics_visible = is_visible

        if is_visible:
            self._layout.setStretch(3, 1)
            self._layout.setStretch(2, 0)
        else:
            self._layout.setStretch(3, 0)
            self._layout.setStretch(2, 1)

    def _create_connection_panel(self):
        port_layout = QHBoxLayout()

        port_layout.setContentsMargins(8, 8, 8, 8)

        port_layout.setSpacing(8)

        port_layout.addWidget(QLabel("Port:"))

        self._port_combobox = ATSerialPortComboBox(port=self._app_view_model.user_settings.port)
        self._port_combobox.setMinimumWidth(140)
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

        panel = CardWidget(background_color=None, header_background_color="#00b6de")
        panel.setContentLayout(port_layout)

        header = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("Connection")
        title.setStyleSheet("font-weight: bold; color: white")
        layout.addWidget(title)

        layout.addStretch(1)

        self._connection_status = QLabel("Not Connected")
        self._connection_status.setStyleSheet("color: white")
        self._connection_status.setContentsMargins(0, 0, 4, 0)
        layout.addWidget(self._connection_status)

        header.setLayout(layout)

        panel.header.setContent(header)

        return panel

    def _port_selection_changed(self, _index: int):
        if not self._ignore_port_changes and len(self._port_combobox.currentText()) > 0:
            self._app_view_model.user_settings.set_port(self._port_combobox.currentText())

    def _connect(self):
        if self._app_view_model.is_connected:
            self._app_view_model.disconnect_from_device()
            self._connect_button.setText("Connect")
            self._connection_status.setText("Not Connected")
            self.disconnected.emit()
        else:
            self.connecting.emit()
            self._connection_status.setText("Pellet Module Version: Waiting for response...")
            self._app_view_model.connect_to_device()
            self._connect_button.setText("Disconnect")

        self._pellet_control.setEnabled(self._app_view_model.is_connected)
        self._port_combobox.setEnabled(not self._app_view_model.is_connected)
        self._refresh_button.setEnabled(not self._app_view_model.is_connected)

    def _model_property_changed(self, name: str, value: object, _: object):
        if name == "command_pending":
            self._pellet_control.setEnabled((not value) and self._app_view_model.is_connected)
            self._port_combobox.setEnabled((not value) and self._app_view_model.is_connected)
            self._refresh_button.setEnabled((not value) and self._app_view_model.is_connected)
            self._connect_button.setEnabled((not value) and self._app_view_model.is_connected)
        elif name == "firmware_version":
            self._connection_status.setText(f"Pellet Module Version: {value}")
