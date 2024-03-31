from PySide6.QtWidgets import QLabel, QLineEdit, QGridLayout, QSpinBox, QWidget, QComboBox

from autotrainer.pg_widget import PGWidget

from tools.acquisition.model.head_fix_model import HeadFixModel


class HeadFixContent(QGridLayout):
    def __init__(self, model: HeadFixModel):
        super().__init__()

        self._model = model

        self.setContentsMargins(10, 10, 10, 10)

        self.addWidget(QLabel("Port:"))

        self._port_combobox = QComboBox()

        self._refresh_ports()

        self._port_combobox.currentIndexChanged.connect(self._port_selection_changed)
        self.addWidget(self._port_combobox, 0, 1)

        self.addWidget(QLabel("Position:"), 0, 2)

        self._position = QSpinBox()
        self._position.setMaximum(100)
        self._position.setWrapping(False)
        self._position.valueChanged.connect(self._update_position)
        self.addWidget(self._position, 0, 3)

        self.addWidget(QLabel("Load Cell Trigger (mg):"), 0, 4)
        self._load_cell = QLineEdit()
        self._load_cell.editingFinished.connect(self._update_trigger)
        self._load_cell.setText(str(self._model.load_trigger))
        self.addWidget(self._load_cell, 0, 5)

        self.addWidget(QWidget(), 0, 6)
        self.setColumnStretch(6, 1)

        self._plot1 = PGWidget()
        self._plot1.setBackground(None)
        self._plot1.setMaximumHeight(160)
        self._model.measurements.weight_ready.connect(self._plot1.update_plot)
        self.addWidget(self._plot1, 1, 0, 1, 7)

    def setCaptureEnabled(self, enabled: bool):
        self._port_combobox.setEnabled(enabled)

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

    def _update_position(self):
        self._model.update_position(self._position.value())

    def _update_trigger(self):
        try:
            self._model.load_trigger = int(self._load_cell.text())
        except:
            pass
