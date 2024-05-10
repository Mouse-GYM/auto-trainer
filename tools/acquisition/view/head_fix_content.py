import time
import logging

from PySide6.QtWidgets import QLabel, QLineEdit, QGridLayout, QSpinBox, QWidget, QComboBox, QPushButton

from autotrainer.PGWidget import PGWidget

from tools.acquisition.model.head_fix_model import HeadFixModel

logger = logging.getLogger(__name__)


class HeadFixContent(QGridLayout):
    def __init__(self, model: HeadFixModel):
        super().__init__()

        self._model = model

        self.setContentsMargins(8, 8, 8, 8)

        self.addWidget(QLabel("Port:"))

        self._port_combobox = QComboBox()
        self._port_combobox.currentIndexChanged.connect(self._port_selection_changed)
        self.addWidget(self._port_combobox, 0, 1)

        self.addWidget(QLabel("Position:"), 0, 2)

        self._position = QSpinBox()
        self._position.setMaximum(100)
        self._position.setWrapping(False)
        self._position.valueChanged.connect(self._update_position)
        self.addWidget(self._position, 0, 3)

        self.addWidget(QLabel("Load Cell Trigger (g):"), 0, 4)
        self._load_cell = QLineEdit()
        self._load_cell.editingFinished.connect(self._update_trigger)
        self._load_cell.setText(str(self._model.load_trigger))
        self.addWidget(self._load_cell, 0, 5)

        self.addWidget(QWidget(), 0, 6)
        self.setColumnStretch(6, 1)

        self._tare_button = QPushButton("Tare")
        self._tare_button.setEnabled(False)
        self._tare_button.clicked.connect(self._model.tare)
        self.addWidget(self._tare_button, 0, 7)

        self._plot1 = PGWidget()
        self._plot1.setBackground(None)
        self._plot1.setMaximumHeight(160)
        self._plot1.getViewBox().setRange(yRange=[0, 50])
        self._model.measurements.weight_ready.connect(self._weight_received)
        self.addWidget(self._plot1, 1, 0, 1, 7)

        self._measurement_count = 0
        self._start = None

        self._refresh_ports()

    def use_cache(self):
        self._plot1.use_cache()

    def setCaptureEnabled(self, enabled: bool):
        self._port_combobox.setEnabled(enabled)
        self._tare_button.setEnabled(not enabled)

        if not enabled:            
            self._measurement_count = 0

    def _weight_received(self, values):
        if self._measurement_count == 0:
            self._start = time.perf_counter_ns()
            
        self._measurement_count += len(values)

        if self._measurement_count % 1000 == 0:
            logger.info(f"<head fix content>{(1e9 * self._measurement_count/ (time.perf_counter_ns() - self._start)):.1f} mps")

        self._plot1.cache_data(values)

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
