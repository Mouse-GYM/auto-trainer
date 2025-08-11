from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QFormLayout

from autotrainer.pyside import CardWidget, StatusIcon
from tools.acquisition.model.hardware_model import HardwareModel

from tools.acquisition.view.content_widget import ContentWidget


class AlarmContent(ContentWidget):
    """
    Widget to display alarm content.
    """
    front_door_changed = Signal(bool, name="front_door_changed")
    slide_door_changed = Signal(bool, name="slide_door_changed")

    def __init__(self, hardware_model: HardwareModel):
        super().__init__()

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
        self._audio_spectrum_status = StatusIcon.alarmIcon()
        form_layout.addRow("Audio Spectrum:", self._audio_spectrum_status)
        self._missing_status = StatusIcon.alarmIcon()
        form_layout.addRow("Missing:", self._missing_status)

        label = QLabel("Device")
        label.setStyleSheet("font-weight: bold; margin-top: 12px;")
        form_layout.addRow(label, None)

        self._front_door_status = StatusIcon.doorIcon()
        form_layout.addRow("Front Door:", self._front_door_status)
        self._slide_door_status = StatusIcon.doorIcon()
        form_layout.addRow("Slide Door:", self._slide_door_status)

        content_layout.addLayout(form_layout)

        self._card_widget.setContentLayout(content_layout)

        layout = QVBoxLayout()
        layout.addWidget(self._card_widget)
        self.setLayout(layout)

        self.front_door_changed.connect(lambda b: self._front_door_status.setStatus(b))
        self.slide_door_changed.connect(lambda b: self._slide_door_status.setStatus(b))

        self._hardware_model.property_changed += self._model_property_changed

    def set_is_capture_active(self, is_editable: bool):
        self._card_widget.setEnabled(is_editable)

    def _model_property_changed(self, property_name: str, value, old_value):
        if property_name == HardwareModel.FRONT_DOOR_PROPERTY:
            self.front_door_changed.emit(value)
        elif property_name == HardwareModel.SLIDE_DOOR_PROPERTY:
            self.slide_door_changed.emit(value)
