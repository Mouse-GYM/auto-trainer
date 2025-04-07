import logging

from PySide6.QtCore import Qt, Signal, QTimer, Slot
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget, QGridLayout, QHBoxLayout, QPushButton, QLabel, QSpinBox, \
    QCheckBox, QLineEdit, QFileDialog, QPlainTextEdit, QVBoxLayout

import qtawesome as qta

from autotrainer.core import PerfMonitor
from autotrainer.core.project import ProjectInfo
from autotrainer.pyside import PGWidget, ATSerialPortComboBox, CardWidget, TextBoxHandler

logger = logging.getLogger(__name__)


class MainContent(QWidget):
    connecting = Signal()
    disconnected = Signal()

    def __init__(self, model):
        super().__init__()

        self._model = model

        self._ignore_port_changes = False

        self._is_diagnostics_visible = True

        self._plots = []

        layout = QVBoxLayout()

        layout.addWidget(self._create_connection_panel())

        layout.addWidget(self._create_control_panel())

        layout.addWidget(self._create_sensor_panel())

        layout.addWidget(self._create_diagnostics_panel())

        layout.setStretch(3, 1)

        self._layout = layout

        self.setLayout(layout)

        self._refresh_ports()

        # The combination of PySide6/Qt signals and slots and the Jetson has reasonable performance, but with a basic
        # implementation does not keep up with 100Hz updates.  We don't need to see 100Hz updates on screen, so rather
        # than optimize that pipeline, just use a timer to refresh the data at an acceptable rate.
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh_data)
        self._timer.start(100)

        self._perf_monitor = PerfMonitor(name="<HeadFixUI>", units="mps", report_count=3000)

        handler = TextBoxHandler(self._diagnostics)
        handler.setFormatter(logging.Formatter(fmt="%(asctime)s: %(levelname)s: %(name)s: %(message)s"))
        logging.getLogger("autotrainer").addHandler(handler)

    @Slot()
    def refresh_data(self):
        for plot in self._plots:
            plot.use_cache()

    @property
    def is_diagnostics_visible(self) -> bool:
        return self._is_diagnostics_visible

    def on_activated(self):
        self._model.property_changed += self._model_property_changed
        self._model.message_handler.measurement_callback = self._measurements_received
        self._model.message_handler.audio_callback = self._audio_spectrum_received
        self._model.analysis.property_changed += self._analysis_property_changed

    def set_diagnostics_visible(self, is_visible: bool):
        self._diagnostics_panel.setVisible(is_visible)
        self._is_diagnostics_visible = is_visible

        if is_visible:
            self._layout.setStretch(3, 1)
            self._layout.setStretch(2, 0)
        else:
            self._layout.setStretch(3, 0)
            self._layout.setStretch(2, 1)

    # noinspection PyMethodMayBeStatic
    def _create_connection_panel(self):
        port_layout = QHBoxLayout()

        port_layout.setContentsMargins(8, 8, 8, 8)

        port_layout.setSpacing(8)

        port_layout.addWidget(QLabel("Port:"))

        self._port_combobox = ATSerialPortComboBox(port=self._model.user_settings.port)
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
        panel.header.setTitle("Connection", "white")

        return panel

    def _create_control_panel(self):
        row_layout = QHBoxLayout()
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(32)

        position_layout = QHBoxLayout()
        position_layout.setContentsMargins(8, 8, 8, 8)
        position_layout.setSpacing(8)

        self._update_position_button = QPushButton("Set Intensity")
        self._update_position_button.setEnabled(False)
        self._update_position_button.clicked.connect(self._set_position)
        position_layout.addWidget(self._update_position_button, 0)

        self._position = QSpinBox()
        self._position.setMaximum(100)
        self._position.setValue(0)
        self._position.setWrapping(False)
        self._position.setEnabled(False)
        position_layout.addWidget(self._position, 0, Qt.AlignLeft)

        position_layout.addStretch(1)

        self._tare_button = QPushButton("Tare")
        self._tare_button.setEnabled(False)
        self._tare_button.clicked.connect(self._model.tare)
        position_layout.addWidget(self._tare_button, 0)

        position_layout.addStretch(1)

        row_layout.addLayout(position_layout)

        record_layout = QHBoxLayout()
        record_layout.setContentsMargins(8, 8, 8, 8)
        record_layout.setSpacing(8)

        self._enable_streaming = QCheckBox("Stream measurements")
        self._enable_streaming.setEnabled(True)
        self._enable_streaming.setChecked(self._model.user_settings.stream_enabled)
        self._enable_streaming.stateChanged.connect(lambda x: self._enable_data_stream(x))
        record_layout.addWidget(self._enable_streaming)

        self._record = QCheckBox("Save measurements")
        self._record.setChecked(self._model.user_settings.record_enabled)
        self._record.stateChanged.connect(lambda x: self._update_record_enabled(x))
        record_layout.addWidget(self._record)

        self._record_location = QLineEdit(self._model.user_settings.record_location)
        self._record_location.setMinimumWidth(100)
        record_layout.addWidget(self._record_location, 1)

        self._browse_button = QPushButton("Select...")
        self._browse_button.clicked.connect(self._browse_for_location)
        record_layout.addWidget(self._browse_button)

        row_layout.addLayout(record_layout, 1.0)

        panel = CardWidget(background_color=None, header_background_color="#00b6de")
        panel.setContentLayout(row_layout)

        header = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("Control")
        title.setStyleSheet("font-weight: bold; color: white")
        layout.addWidget(title)

        layout.addStretch(1)

        label = QLabel("Current Intensity:")
        label.setStyleSheet("color: white")
        layout.addWidget(label)
        self._current_intensity = QLabel("(no updates)")
        self._current_intensity.setStyleSheet("color: white")
        self._current_intensity.setContentsMargins(0, 0, 4, 0)
        layout.addWidget(self._current_intensity)

        header.setLayout(layout)

        panel.header.setContent(header)

        return panel

    def _create_sensor_panel(self):
        plot_layout = QGridLayout()
        plot_layout.setContentsMargins(8, 0, 8, 0)

        self._load_cell_plot, widget = self._create_plot_widget("Load Cell (g)")
        self._load_cell_plot.setYRange(0, 50)
        plot_layout.addWidget(widget, 0, 0)

        self._headbar_pressure_plot, widget = self._create_plot_widget("Headbar Pressure (Raw A/D)")
        self._headbar_pressure_plot.setYRange(0, 1024)
        plot_layout.addWidget(widget, 0, 1)

        self._head_contact_plot, widget = self._create_plot_widget("Head Contact (On/Off)")
        self._head_contact_plot.setYRange(0, 1)
        plot_layout.addWidget(widget, 2, 0)

        self._audio_spectrum_plot, widget = self._create_plot_widget("Audio Spectrum (dB)")
        plot_layout.addWidget(widget, 2, 1)

        self._temperature_plot, widget = self._create_plot_widget("Temperature (\u00b0C)")
        self._temperature_plot.setYRange(0, 50)
        plot_layout.addWidget(widget, 3, 0)

        self._humidity_plot, widget = self._create_plot_widget("Relative Humidity (%)")
        self._humidity_plot.setYRange(0, 100)
        plot_layout.addWidget(widget, 3, 1)

        panel = CardWidget(background_color=None, header_background_color="#00b6de")
        panel.setContentLayout(plot_layout)
        panel.header.setTitle("Sensor Data", "white")

        return panel

    # noinspection PyMethodMayBeStatic
    def _create_plot_widget(self, title: str):
        plot = PGWidget()
        plot.setBackground(None)
        plot.getPlotItem().getViewBox().setBackgroundColor((220, 220, 220))
        plot.setMaximumHeight(150)
        plot.setTitle(title)

        self._plots.append(plot)

        # pyqtgraph is not always well-behaved with layouts.  Rather than fight it, use a QWidget for normal behavior.
        widget = QWidget()
        widget.setLayout(QHBoxLayout())
        widget.layout().addWidget(plot)

        return plot, widget

    def _create_diagnostics_panel(self):
        self._diagnostics = QPlainTextEdit()
        self._diagnostics.setReadOnly(True)
        self._diagnostics.setStyleSheet("border: none")

        panel = CardWidget(header_background_color="#00b6de")
        panel.setContentWidget(self._diagnostics)
        panel.header.setTitle("Logs", "white")

        self._diagnostics_panel = panel

        return panel

    def _model_property_changed(self, name, value, _):
        if name == "magnet_intensity":
            self._current_intensity.setText(f"{value}")

    def _analysis_property_changed(self, name, value, _):
        if name == "is_load_cell_engaged":
            if value:
                self._load_cell_plot.getPlotItem().getViewBox().setBackgroundColor((0, 250, 154))
            else:
                self._load_cell_plot.getPlotItem().getViewBox().setBackgroundColor((220, 220, 220))
        elif name == "is_headbar_engaged":
            if value:
                self._head_contact_plot.getPlotItem().getViewBox().setBackgroundColor((0, 250, 154))
            else:
                self._head_contact_plot.getPlotItem().getViewBox().setBackgroundColor((220, 220, 220))
        elif name == "is_force_detector_engaged":
            if value:
                self._headbar_pressure_plot.getPlotItem().getViewBox().setBackgroundColor((0, 250, 154))
            else:
                self._headbar_pressure_plot.getPlotItem().getViewBox().setBackgroundColor((220, 220, 220))

    def _measurements_received(self, measurements):
        self._load_cell_plot.cache_data(measurements[0])
        self._head_contact_plot.cache_data(measurements[1])
        self._headbar_pressure_plot.cache_data(measurements[2])
        self._temperature_plot.cache_data(measurements[3])
        self._humidity_plot.cache_data(measurements[4])

        self._perf_monitor.add_cycles(len(measurements[0]))

    def _audio_spectrum_received(self, spectrum):
        self._audio_spectrum_plot.replace(spectrum)

    def _refresh_ports(self):
        ports = self._model.refresh_ports()

        self._port_combobox.refresh_ports(ports)

    def _port_selection_changed(self, _index: int):
        if not self._ignore_port_changes and len(self._port_combobox.currentText()) > 0:
            self._model.user_settings.set_port(self._port_combobox.currentText())

    def _set_position(self):
        self._model.set_position(self._position.value())

    def _update_record_enabled(self, b: bool):
        self._model.user_settings.record_enabled = b

    def _enable_data_stream(self, b: bool):
        self._model.set_stream_enabled(b)

    def _connect(self):
        if self._model.is_connected:
            self._model.disconnect_from_device()
            self._model.analysis.project_info = None
            self._connect_button.setText("Connect")
            self.disconnected.emit()
        else:
            self.connecting.emit()
            self._load_cell_plot.reset()
            self._head_contact_plot.reset()
            self._headbar_pressure_plot.reset()
            self._temperature_plot.reset()
            self._humidity_plot.reset()

            if self._record.isChecked():
                self._model.analysis.project_info = ProjectInfo(
                    root=self._record_location.text(),
                    device_id="HeadFixUI",
                    ensure_exists=True)
            else:
                self._model.analysis.project_info = None

            self._model.connect_to_device()
            self._perf_monitor.reset()
            self._connect_button.setText("Disconnect")
            self._current_intensity.setText("(no updates)")

        self._position.setEnabled(self._model.is_connected)
        self._tare_button.setEnabled(self._model.is_connected)
        self._update_position_button.setEnabled(self._model.is_connected)
        self._load_cell_plot.setEnabled(self._model.is_connected)
        self._head_contact_plot.setEnabled(self._model.is_connected)
        self._headbar_pressure_plot.setEnabled(self._model.is_connected)
        self._temperature_plot.setEnabled(self._model.is_connected)
        self._humidity_plot.setEnabled(self._model.is_connected)
        self._port_combobox.setEnabled(not self._model.is_connected)
        self._refresh_button.setEnabled(not self._model.is_connected)
        self._record.setEnabled(not self._model.is_connected)
        self._record_location.setEnabled(not self._model.is_connected)
        self._browse_button.setEnabled(not self._model.is_connected)

    def _browse_for_location(self):
        dirname = QFileDialog.getExistingDirectory(self, "Select Directory",
                                                   self._record_location.text())

        if len(dirname) > 0:
            self._record_location.setText(dirname)
            self._model.user_settings.record_location = dirname
