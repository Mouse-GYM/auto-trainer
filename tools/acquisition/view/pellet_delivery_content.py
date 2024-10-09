from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget, QHBoxLayout, QPushButton

from autotrainer.device import SerialInterface
from autotrainer.pyside import ATSerialPortComboBox, CardWidget
from tools.acquisition.model.pellet_delivery_model import PelletDeliveryModel
from tools.acquisition.view.content_widget import ContentWidget
from tools.acquisition.view.pellet_control_content import PelletControlContent


class PelletDeliveryContent(ContentWidget):
    def __init__(self, model: PelletDeliveryModel):
        super().__init__()

        self._model = model

        self._card_widget = CardWidget()

        self._pellet_control = PelletControlContent(self._model)
        self._card_widget.setContentWidget(self._pellet_control)

        # Header
        self._header = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("Pellet Delivery")
        title.setStyleSheet("font-weight: bold")
        layout.addWidget(title)

        layout.addStretch(1)

        layout.addWidget(QLabel("Port:"))

        self._port_combobox = ATSerialPortComboBox(port=self._model.port)
        self._port_combobox.currentIndexChanged.connect(self._port_selection_changed)
        layout.addWidget(self._port_combobox)

        self._port_label = QLabel(self._model.port)
        self._port_label.setContentsMargins(0, 0, 4, 0)
        layout.addWidget(self._port_label)

        self._header.setLayout(layout)

        self._card_widget.header.setContent(self._header)

        # Footer
        self._footer = QWidget()

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addStretch(1)

        self._home_button = QPushButton("Home")
        self._home_button.clicked.connect(lambda: self._model.send_home())
        layout.addWidget(self._home_button)

        self._load_button = QPushButton("Load")
        self._load_button.clicked.connect(lambda: self._model.load_pellet())
        layout.addWidget(self._load_button)

        self._send_button = QPushButton("Send")
        self._send_button.clicked.connect(lambda: self._model.send_pellet())
        layout.addWidget(self._send_button)

        self._release_button = QPushButton("Release")
        self._release_button.clicked.connect(lambda: self._model.release_pellet())
        layout.addWidget(self._release_button)

        self._footer.setLayout(layout)

        self._card_widget.footer.setContent(self._footer)

        # Final layout
        layout = QVBoxLayout()
        layout.addWidget(self._card_widget)
        self.setLayout(layout)

        self._refresh_ports()

        self._model.property_changed += self._model_property_changed

        self.set_is_editable(False)

    def on_activated(self):
        self._model.on_activated()

    def set_is_editable(self, is_editable: bool):
        self._port_combobox.setVisible(is_editable)
        self._port_label.setVisible(not is_editable)
        self._footer.setEnabled(not is_editable)

    def set_is_capture_active(self, is_active: bool):
        self._pellet_control.setEnabled(is_active)
        self._port_combobox.setEnabled(not is_active)

    def _refresh_ports(self):
        ports = SerialInterface.refresh_ports()

        self._port_combobox.refresh_ports(ports)

    def _port_selection_changed(self, _index: int):
        if len(self._port_combobox.currentText()) > 0:
            self._model.port = self._port_combobox.currentText()
        else:
            self._model.port = None

    def _model_property_changed(self, name, value, _):
        if name == "port":
            self._port_combobox.select_port(value)
            self._port_label.setText(value)
