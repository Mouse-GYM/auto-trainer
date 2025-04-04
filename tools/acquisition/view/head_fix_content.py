import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QLineEdit, QSpinBox, QWidget, QPushButton, QVBoxLayout, QHBoxLayout

from autotrainer.core import PerfMonitor
from autotrainer.pyside import PGWidget, ATSerialPortComboBox, CardWidget, QtIndicator

from tools.acquisition.model.head_fix_model import HeadFixModel
from tools.acquisition.view.content_widget import ContentWidget

logger = logging.getLogger(__name__)

_ACTIVE_LOAD_CELL_COLOR = (0, 250, 154)
_INACTIVE_LOAD_CELL_COLOR = (240, 240, 240)


class HeadFixContent(ContentWidget):
    position_changed = Signal(int)

    def __init__(self, model: HeadFixModel):
        super().__init__()

        self._model = model

        self._card_widget = CardWidget()

        content = QWidget()
        content.setLayout(QHBoxLayout())

        self._plot1 = PGWidget()
        self._plot1.setBackground("w")
        self._plot1.getPlotItem().getViewBox().setBackgroundColor(_INACTIVE_LOAD_CELL_COLOR)
        self._plot1.setMinimumHeight(140)
        self._plot1.getViewBox().setRange(yRange=[0, 50])
        self._plot1.scale_x = 100.0

        self._plot1.getAxis("left").setLabel("Weight (g)")
        ticks = [0, 10, 25, 40, 50]
        self._plot1.getAxis("left").setTicks([[(tick, str(tick)) for tick in ticks]])
        self._plot1.getAxis("bottom").setLabel("Time (s)")

        content.layout().addWidget(self._plot1)

        self._card_widget.setContentWidget(content)

        # Header
        self._header = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = QLabel("Head Fix")
        title.setStyleSheet("font-weight: bold")
        layout.addWidget(title)

        layout.addSpacing(10)

        layout.addWidget(QLabel("Baseline: "))
        self._baseline = QLabel("0")
        layout.addWidget(self._baseline)

        layout.addStretch(1)

        self._headbar_engaged = QtIndicator(text="Headbar")
        layout.addWidget(self._headbar_engaged)

        self._load_cell_engaged = QtIndicator(text="Load Cell")
        layout.addWidget(self._load_cell_engaged)

        self._force_detector_engaged = QtIndicator(text="Force Detector")
        layout.addWidget(self._force_detector_engaged)

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

        layout.addWidget(QLabel("Current Intensity:"))

        self._current_position = QLabel("0")
        layout.addWidget(self._current_position)

        self._baseline_button = QPushButton("Set as Baseline")
        self._baseline_button.clicked.connect(lambda: self._model.set_current_as_baseline())
        layout.addWidget(self._baseline_button)

        layout.addWidget(QLabel("Move To:"))

        self._position = QSpinBox()
        self._position.setValue(self._model.position)
        self._position.setMaximum(100)
        self._position.setWrapping(False)
        self._position.valueChanged.connect(self._update_position)
        layout.addWidget(self._position)

        layout.addStretch(1)

        layout.addWidget(QLabel("Load Cell Trigger (g):"))
        self._load_cell = QLineEdit()
        self._load_cell.editingFinished.connect(self._update_trigger)
        self._load_cell.setText(str(self._model.load_trigger))
        layout.addWidget(self._load_cell)

        self._tare_button = QPushButton("Tare")
        self._tare_button.setEnabled(False)
        self._tare_button.clicked.connect(self._model.tare)
        layout.addWidget(self._tare_button)

        self._footer.setLayout(layout)

        self._card_widget.footer.setContent(self._footer)

        # Final layout
        layout = QVBoxLayout()
        layout.addWidget(self._card_widget)
        self.setLayout(layout)

        self._perf_monitor = PerfMonitor(name="headFixContent", units="mps", report_count=3000)

        self._refresh_ports()

        self._model.property_changed += self._model_property_changed

        self.set_is_editable(False)

        self.position_changed.connect(lambda x: self._current_position.setText(str(x)))

    def on_activated(self):
        self._model.on_activated()
        self._model.message_handler.measurement_callback = self._weight_received

    def set_is_editable(self, is_editable: bool):
        self._port_combobox.setVisible(is_editable)
        self._port_label.setVisible(not is_editable)

    def set_is_capture_active(self, is_active: bool):
        self._port_combobox.setEnabled(not is_active)
        self._tare_button.setEnabled(is_active)

        if is_active:
            self._perf_monitor.reset()

    def use_cache(self):
        self._plot1.use_cache()

        self._load_cell_engaged.setState(self._model.is_load_cell_engaged)
        self._headbar_engaged.setState(self._model.is_headbar_engaged)
        self._force_detector_engaged.setState(self._model.is_force_detector_engaged)

    def _weight_received(self, value):
        values = value[0]

        self._perf_monitor.add_cycles(len(values))

        self._plot1.cache_data(values)

    def _refresh_ports(self):
        if self._model is not None:
            ports = self._model.refresh_ports()
        else:
            ports = []

        self._port_combobox.refresh_ports(ports)

    def _port_selection_changed(self, _index: int):
        if len(self._port_combobox.currentText()) > 0:
            self._model.port = self._port_combobox.currentText()
        else:
            self._model.port = None

    def _update_position(self):
        self._model.set_position(self._position.value())

    def _update_trigger(self):
        try:
            self._model.load_trigger = int(self._load_cell.text())
        except:
            pass

    def _model_property_changed(self, name, value, _):
        if name == "port":
            self._port_combobox.select_port(value)
            self._port_label.setText(value)
        elif name == "load_trigger":
            self._load_cell.setText(str(value))
        elif name == "position":
            self.position_changed.emit(value)
        elif name == "baseline_intensity":
            self._baseline.setText(str(value))
        elif name == "is_load_cell_engaged":
            if value:
                self._plot1.getPlotItem().getViewBox().setBackgroundColor(_ACTIVE_LOAD_CELL_COLOR)
            else:
                self._plot1.getPlotItem().getViewBox().setBackgroundColor(_INACTIVE_LOAD_CELL_COLOR)
