import logging
import time

from PySide6.QtCore import Qt, Signal, QTimer, Slot
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget, QGridLayout, QHBoxLayout, QPushButton, QLabel, QSpinBox, \
    QCheckBox, QLineEdit, QFileDialog

import qtawesome as qta

from autotrainer.core.project import ProjectInfo
from autotrainer.device import SerialInterface
from autotrainer.pyside import PGWidget, ATSerialPortComboBox
from autotrainer.pyside import ATSeparator

logger = logging.getLogger(__name__)


class MainContent(QWidget):
    connecting = Signal()
    disconnected = Signal()

    def __init__(self, app_view_model):
        super().__init__()

        self._app_view_model = app_view_model

        self._ignore_port_changes = False

        layout = QGridLayout()

        layout.setContentsMargins(0, 0, 0, 0)

        # Row 1

        port_layout = QHBoxLayout()

        port_layout.setContentsMargins(8, 8, 8, 8)

        port_layout.setSpacing(8)

        port_layout.addWidget(QLabel("Port:"))

        self._port_combobox = ATSerialPortComboBox(port=self._app_view_model.user_settings.port)
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

        layout.addLayout(port_layout, 0, 0, 1, 2)

        # Row 2

        layout.addWidget(ATSeparator("#b9b9b9"), 1, 0, 1, 2)

        # Row 3

        row_layout = QHBoxLayout()
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(32)

        position_layout = QHBoxLayout()
        position_layout.setContentsMargins(8, 8, 8, 8)
        position_layout.setSpacing(8)

        position_layout.addWidget(QLabel("Position:"), 0)

        self._position = QSpinBox()
        self._position.setMaximum(100)
        self._position.setValue(50)
        self._position.setWrapping(False)
        self._position.valueChanged.connect(self._update_position)
        self._position.setEnabled(False)
        position_layout.addWidget(self._position, 0, Qt.AlignLeft)

        self._tare_button = QPushButton("Tare")
        self._tare_button.setEnabled(False)
        self._tare_button.clicked.connect(self._app_view_model.tare)
        position_layout.addWidget(self._tare_button, 0)

        position_layout.addStretch(1)

        row_layout.addLayout(position_layout)

        record_layout = QHBoxLayout()
        record_layout.setContentsMargins(8, 8, 8, 8)
        record_layout.setSpacing(8)

        self._enable_streaming = QCheckBox("Stream measurements")
        self._enable_streaming.setEnabled(True)
        self._enable_streaming.setChecked(self._app_view_model.user_settings.stream_enabled)
        self._enable_streaming.stateChanged.connect(lambda x: self._update_stream_enabled(x))
        record_layout.addWidget(self._enable_streaming)

        self._record = QCheckBox("Save measurements")
        self._record.setChecked(self._app_view_model.user_settings.record_enabled)
        self._record.stateChanged.connect(lambda x: self._update_record_enabled(x))
        record_layout.addWidget(self._record)

        self._record_location = QLineEdit(self._app_view_model.user_settings.record_location)
        self._record_location.setMinimumWidth(100)
        record_layout.addWidget(self._record_location, 1)

        self._browse_button = QPushButton("Select...")
        self._browse_button.clicked.connect(self._browse_for_location)
        record_layout.addWidget(self._browse_button)

        row_layout.addLayout(record_layout, 1.0)

        layout.addLayout(row_layout, 2, 0, 1, 2)

        # Row 4

        layout.addWidget(ATSeparator("#b9b9b9"), 3, 0, 1, 2)

        # Row 5 and beyond

        self._plot1 = PGWidget()
        self._plot1.setBackground(None)
        self._plot1.setMaximumHeight(150)
        self._plot1.setTitle("Weight")
        self._plot1.getViewBox().setRange(yRange=[0, 50])
        layout.addWidget(self._plot1, 4, 0)

        self._plot2 = PGWidget()
        self._plot2.setBackground(None)
        self._plot2.setMaximumHeight(150)
        self._plot2.setTitle("Switch")
        layout.addWidget(self._plot2, 5, 0)

        self._plot3 = PGWidget()
        self._plot3.setBackground(None)
        self._plot3.setMaximumHeight(150)
        self._plot3.setTitle("Pressure")
        layout.addWidget(self._plot3, 6, 0)

        self._plot4 = PGWidget()
        self._plot4.setBackground(None)
        self._plot4.setMaximumHeight(150)
        self._plot4.setTitle("Temperature")
        layout.addWidget(self._plot4, 5, 1)

        self._plot5 = PGWidget()
        self._plot5.setBackground(None)
        self._plot5.setMaximumHeight(150)
        self._plot5.setTitle("Humidity")
        layout.addWidget(self._plot5, 6, 1)

        layout.setRowStretch(7, 1)

        layout.addWidget(ATSeparator("#b9b9b9"), 8, 0, 1, 2)

        self.setLayout(layout)

        self._refresh_ports()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh_data)
        self._timer.start(100)

        self._measurement_count = 0
        self._start = None

    @Slot()
    def refresh_data(self):
        self._plot1.use_cache()
        self._plot2.use_cache()
        self._plot3.use_cache()
        self._plot4.use_cache()
        self._plot5.use_cache()

    def on_activated(self):
        self._app_view_model.head_fix_reader.measurement_callback = self._measurements_received

    def _measurements_received(self, measurements):
        self._plot1.cache_data(measurements[0])
        self._plot2.cache_data(measurements[1])
        self._plot3.cache_data(measurements[2])
        self._plot4.cache_data(measurements[3])
        self._plot5.cache_data(measurements[4])

        self._measurement_count += len(measurements[0])

        if self._start is None:
            self._start = time.perf_counter_ns()

        if self._measurement_count % 3000 == 0:
            logger.info(f"{(1e9 * self._measurement_count / (time.perf_counter_ns() - self._start)):.1f} mps")

    def _refresh_ports(self):
        ports = SerialInterface.refresh_ports()

        self._port_combobox.refresh_ports(ports)

    def _port_selection_changed(self, _index: int):
        if not self._ignore_port_changes and len(self._port_combobox.currentText()) > 0:
            self._app_view_model.user_settings.set_port(self._port_combobox.currentText())

    def _update_position(self):
        self._app_view_model.update_position(self._position.value())

    def _update_record_enabled(self, b: bool):
        self._app_view_model.user_settings.record_enabled = b

    def _update_stream_enabled(self, b: bool):
        self._app_view_model.set_stream_enabled(b)

    def _connect(self):
        if self._app_view_model.is_connected:
            self._app_view_model.disconnect_from_device()
            self._app_view_model.head_fix_reader.project_info = None
            self._connect_button.setText("Connect")
            self.disconnected.emit()
        else:
            self.connecting.emit()
            self._plot1.reset()
            self._plot2.reset()
            self._plot3.reset()
            self._plot4.reset()
            self._plot5.reset()
            if self._record.isChecked():
                self._app_view_model.head_fix_reader.project_info = ProjectInfo(self._record_location.text(), "")
            else:
                self._app_view_model.head_fix_reader.project_info = None
            self._app_view_model.connect_to_device()
            self._start = time.perf_counter_ns()
            self._measurement_count = 0
            self._connect_button.setText("Disconnect")

        self._position.setEnabled(self._app_view_model.is_connected)
        self._tare_button.setEnabled(self._app_view_model.is_connected)
        self._plot1.setEnabled(self._app_view_model.is_connected)
        self._plot2.setEnabled(self._app_view_model.is_connected)
        self._plot3.setEnabled(self._app_view_model.is_connected)
        self._plot4.setEnabled(self._app_view_model.is_connected)
        self._plot5.setEnabled(self._app_view_model.is_connected)
        self._port_combobox.setEnabled(not self._app_view_model.is_connected)
        self._refresh_button.setEnabled(not self._app_view_model.is_connected)
        self._record.setEnabled(not self._app_view_model.is_connected)
        self._record_location.setEnabled(not self._app_view_model.is_connected)
        self._browse_button.setEnabled(not self._app_view_model.is_connected)

    def _browse_for_location(self):
        dirname = QFileDialog.getExistingDirectory(self, "Select Directory", self._record_location.text())

        if len(dirname) > 0:
            self._record_location.setText(dirname)
            self._app_view_model.user_settings.record_location = dirname
