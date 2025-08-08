from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QLabel, QHBoxLayout, QPushButton
from PySide6.QtGui import QIcon
import qtawesome as qta

from autotrainer.device import get_available_hardware

from .HardwarePortComboBox import HardwarePortComboBox

from ..CardWidget import CardWidget


class ConnectionPanel(QWidget):
    connecting = Signal()
    disconnected = Signal()

    def __init__(self, app_view_model, allow_emulation: bool = False):
        super().__init__()

        self._app_view_model = app_view_model
        self._app_view_model.property_changed += self._model_property_changed

        self._allow_emulation = allow_emulation

        self._ignore_port_changes = False

        layout = QHBoxLayout()
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        layout.addWidget(QLabel("Port:"))

        self._port_combobox = HardwarePortComboBox(port=self._app_view_model.user_settings.port)
        self._port_combobox.setMinimumWidth(140)
        self._port_combobox.currentIndexChanged.connect(self._port_selection_changed)

        layout.addWidget(self._port_combobox, 0)

        self._refresh_button = QPushButton("")
        self._refresh_button.setIcon(QIcon(qta.icon('fa5s.redo')))
        self._refresh_button.clicked.connect(self._refresh_ports)

        layout.addWidget(self._refresh_button, 0)

        layout.addWidget(QWidget(), 1)

        self._connect_button = QPushButton("Connect")
        self._connect_button.clicked.connect(self._connect)
        layout.addWidget(self._connect_button, 0, Qt.AlignRight)

        self._connection_status = QLabel("Not Connected")
        self._connection_status.setStyleSheet("color: white")
        self._connection_status.setContentsMargins(0, 0, 4, 0)

        panel = CardWidget(title="Connection", content_layout=layout, header_right_layout=self._connection_status)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(panel)
        self.setLayout(layout)

        self._refresh_ports()

    def _port_selection_changed(self, _index: int):
        if not self._ignore_port_changes and len(self._port_combobox.currentText()) > 0:
            self._app_view_model.user_settings.set_port(self._port_combobox.currentText())

    def _refresh_ports(self):
        ports = get_available_hardware(allow_can_emulation=self._allow_emulation)
        self._port_combobox.refresh_ports(ports)

    def _connect(self):
        if self._app_view_model.is_connected:
            self._app_view_model.disconnect_from_device()
            self._connect_button.setText("Connect")
            self._connection_status.setText("Not Connected")
            self.disconnected.emit()
        else:
            self.connecting.emit()
            self._connection_status.setText("...")
            self._app_view_model.connect_to_device()
            self._connect_button.setText("Disconnect")

        self._port_combobox.setEnabled(not self._app_view_model.is_connected)
        self._refresh_button.setEnabled(not self._app_view_model.is_connected)

    def _model_property_changed(self, name: str, value: object, _: object):
        if name == "command_pending":
            self._port_combobox.setEnabled((not value) and self._app_view_model.is_connected)
            self._refresh_button.setEnabled((not value) and self._app_view_model.is_connected)
            self._connect_button.setEnabled((not value) and self._app_view_model.is_connected)
        elif name == "firmware_version":
            assert isinstance(value, str)
            self._connection_status.setText(f"Firmware: {value}")
