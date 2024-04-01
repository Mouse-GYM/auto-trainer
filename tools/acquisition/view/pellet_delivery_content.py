from PySide6.QtWidgets import QGridLayout, QLabel, QHBoxLayout, QComboBox, QWidget

from tools.acquisition.model.pellet_delivery_model import PelletDeliveryModel
from tools.acquisition.view.pellet_control_content import PelletControlContent


class PelletDeliveryContent(QWidget):
    def __init__(self, model: PelletDeliveryModel):
        super().__init__()

        self._model = model

        self._ignore_port_changes = False

        layout = QGridLayout()

        layout.addWidget(QLabel("Port:"))

        self._port_combobox = QComboBox()
        self._port_combobox.currentIndexChanged.connect(self._port_selection_changed)
        self._port_combobox.currentIndexChanged.connect(self._port_selection_changed)
        layout.addWidget(self._port_combobox, 0, 1)

        self._pellet_control = PelletControlContent(self._model)
        layout.addWidget(self._pellet_control, 1, 0, 1, 3)

        layout.setColumnStretch(2, 1)

        layout.setContentsMargins(8, 8, 8, 8)

        self._refresh_ports()

        self.setLayout(layout)

    def on_activated(self):
        pass

    def _refresh_ports(self):
        self._model.refresh_ports()

        match = -1

        self._ignore_port_changes = True

        self._port_combobox.clear()

        for idx, port in enumerate(self._model.ports):
            self._port_combobox.addItem(port)
            if port == self._model.port:
                match = idx

        self._port_combobox.setCurrentIndex(match)

        self._ignore_port_changes = False

    def _port_selection_changed(self, index: int):
        if not self._ignore_port_changes and len(self._port_combobox.currentText()) > 0:
            self._model.port = self._port_combobox.currentText()

    def setCaptureEnabled(self, enabled: bool):
        self._pellet_control.setEnabled(not enabled)
        self._port_combobox.setEnabled(enabled)
