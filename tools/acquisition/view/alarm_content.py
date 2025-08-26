from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QFormLayout

from autotrainer.behavior.behavior_algorithm import BehaviorAlgoProps
from autotrainer.core import LoadCellMonitor, get_verbose_logger
from autotrainer.core.analysis.audio_spectrum_monitor import AudioSpectrumThrashMonitor
from autotrainer.pyside import CardWidget, StatusIcon
from tools.acquisition.model.app_model import AppModel
from tools.acquisition.model.hardware_model import HardwareModel

from tools.acquisition.view.content_widget import ContentWidget

logger = get_verbose_logger(__name__)


class AlarmContent(ContentWidget):
    """
    Widget to display alarm content.
    """

    load_cell_thrashing_changed = Signal(bool, name="load_cell_thrashing_changed")
    audio_thrashing_changed = Signal(bool, name="audio_thrashing_changed")
    presence_missing_changed = Signal(bool, name="presence_missing_changed")
    front_door_changed = Signal(bool, name="front_door_changed")
    slide_door_changed = Signal(bool, name="slide_door_changed")

    def __init__(self, app_model: AppModel, hardware_model: HardwareModel):
        super().__init__()

        self._app_model = app_model
        self._hardware_model = hardware_model

        self._card_widget = CardWidget(header_background_color="red")

        self._card_widget.header.setTitle("Alarms", color="white")

        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(8, 8, 8, 8)

        form_layout = QFormLayout()
        form_layout.setHorizontalSpacing(24)

        label = QLabel("Animal")
        label.setStyleSheet("font-weight: bold;")
        form_layout.addRow(label, None)

        self._load_cell_status = StatusIcon.alarmIcon()
        form_layout.addRow("Load Cell:", self._load_cell_status)
        self.load_cell_thrashing_changed.connect(self._load_cell_status.setStatus)

        self._audio_spectrum_status = StatusIcon.alarmIcon()
        form_layout.addRow("Audio Spectrum:", self._audio_spectrum_status)
        self.audio_thrashing_changed.connect(self._audio_spectrum_status.setStatus)

        self._presence_missing_status = StatusIcon.alarmIcon()
        form_layout.addRow("Missing:", self._presence_missing_status)
        self.presence_missing_changed.connect(self._presence_missing_status.setStatus)

        label = QLabel("Device")
        label.setStyleSheet("font-weight: bold; margin-top: 12px;")
        form_layout.addRow(label, None)

        self._front_door_status = StatusIcon.doorIcon()
        form_layout.addRow("Front Door:", self._front_door_status)
        self.front_door_changed.connect(self._front_door_status.setStatus)

        self._slide_door_status = StatusIcon.doorIcon()
        form_layout.addRow("Slide Door:", self._slide_door_status)
        self.slide_door_changed.connect(self._slide_door_status.setStatus)

        content_layout.addLayout(form_layout)

        self._card_widget.setContentLayout(content_layout)

        layout = QVBoxLayout()
        layout.addWidget(self._card_widget)
        self.setLayout(layout)

        hardware_model.property_changed += self._model_property_changed
        app_model.analysis.load_cell_monitor.property_changed += self._load_cell_property_changed
        app_model.analysis.audio_thrashing_monitor.property_changed += self._audio_thrashing_property_changed
        app_model.behavior.algorithm.property_changed += self._behavior_algo_property_changed

    def set_is_capture_active(self, is_editable: bool):
        self._card_widget.setEnabled(is_editable)

    def _model_property_changed(self, property_name: str, value, old_value):
        if property_name == HardwareModel.FRONT_DOOR_PROPERTY:
            self.front_door_changed.emit(value)
        elif property_name == HardwareModel.SLIDE_DOOR_PROPERTY:
            self.slide_door_changed.emit(value)

    def _load_cell_property_changed(self, name: str, new_value, old_value):
        if name == LoadCellMonitor.IS_THRASHING_DETECTED_PROPERTY:
            logger.verbose("setting load_cell_thrashing_changed -> %s", new_value)
            self.load_cell_thrashing_changed.emit(new_value)

    def _audio_thrashing_property_changed(self, name, new_value, old_value):
        if name == AudioSpectrumThrashMonitor.AUDIO_THRASHING_DETECTED_PROPERTY:
            self.audio_thrashing_changed.emit(new_value)

    def _behavior_algo_property_changed(self, name, new_value, old_value):
        if name == BehaviorAlgoProps.PRESENCE_MISSING:
            self.presence_missing_changed.emit(new_value)
