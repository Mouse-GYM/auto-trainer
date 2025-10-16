from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QFormLayout

from autotrainer.behavior.behavior_algorithm import BehaviorAlgoProps
from autotrainer.core import LoadCellMonitor, get_verbose_logger
from autotrainer.core.analysis import EmergencyAlarmMonitor
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

    use_load_cell_audio_thrash_changed = Signal(bool)
    load_cell_audio_thrash_changed = Signal(bool)
    use_global_mouse_presence_changed = Signal(bool)
    global_mouse_presence_changed = Signal(bool)
    use_presence_in_cage_after_exit_tunnel_changed = Signal(bool)
    presence_in_cage_after_exit_tunnel_changed = Signal(bool)

    load_cell_thrashing_changed = Signal(bool, name="load_cell_thrashing_changed")
    audio_thrashing_changed = Signal(bool, name="audio_thrashing_changed")
    front_door_changed = Signal(bool, name="front_door_changed")
    slide_door_changed = Signal(bool, name="slide_door_changed")

    def __init__(self, app_model: AppModel, hardware_model: HardwareModel):
        super().__init__()

        self._app_model = app_model
        self._hardware_model = hardware_model

        self._card_widget = CardWidget(header_background_color="red")

        self._card_widget.header.setTitle("Alarms & Detectors", color="white")

        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(8, 8, 8, 8)

        form_layout = QFormLayout()
        form_layout.setHorizontalSpacing(24)

        emergency_alarm = app_model.behavior.analysis.emergency_alarm_monitor
        emergency_alarm_cfg = emergency_alarm.config
        label = QLabel("Alarms")
        label.setStyleSheet("font-weight: bold;")
        form_layout.addRow(label, None)

        icon = self._mouse_missing_status = StatusIcon.alarmIcon()
        label = self._mouse_missing_label = QLabel("Mouse Missing:")
        form_layout.addRow(label, icon)
        self.use_global_mouse_presence_changed.connect(lambda v: self._mouse_missing_label.setStyleSheet("" if v else "color: gray"))
        self.use_global_mouse_presence_changed.emit(emergency_alarm_cfg.use_global_mouse_presence_missing)
        self.global_mouse_presence_changed.connect(icon.setStatus)

        icon = self._mouse_thrashing_status = StatusIcon.alarmIcon()
        label = self._mouse_thrashing_label = QLabel("Thrashing:")
        form_layout.addRow(label, icon)
        self.use_load_cell_audio_thrash_changed.connect(
            lambda v: self._mouse_thrashing_label.setStyleSheet("" if v else "color: gray"))
        self.use_load_cell_audio_thrash_changed.emit(emergency_alarm_cfg.use_audio_load_cell_thrash)
        self.load_cell_audio_thrash_changed.connect(icon.setStatus)

        icon = self._in_cage_after_tunnel_status = StatusIcon.alarmIcon()
        label = self._in_cage_after_tunnel_label = QLabel("Presence In Cage After Tunnel:")
        form_layout.addRow(label, icon)
        self.use_presence_in_cage_after_exit_tunnel_changed.connect(
            lambda v: self._in_cage_after_tunnel_label.setStyleSheet("" if v else "color: gray"))
        self.use_presence_in_cage_after_exit_tunnel_changed.emit(emergency_alarm_cfg.use_presence_missing_after_exit_tunnel)
        self.presence_in_cage_after_exit_tunnel_changed.connect(icon.setStatus)

        #

        label = QLabel("Detectors")
        label.setStyleSheet("font-weight: bold;")
        label.setContentsMargins(0, 12, 0, 0)
        form_layout.addRow(label, None)

        self._load_cell_thrash_status = StatusIcon.alarmIcon()
        form_layout.addRow("Load Cell Thrash:", self._load_cell_thrash_status)
        self.load_cell_thrashing_changed.connect(self._load_cell_thrash_status.setStatus)

        self._audio_spectrum_status = StatusIcon.alarmIcon()
        form_layout.addRow("Audio:", self._audio_spectrum_status)
        self.audio_thrashing_changed.connect(self._audio_spectrum_status.setStatus)

        self._front_door_status = StatusIcon.doorIcon()
        form_layout.addRow("Front Door:", self._front_door_status)
        self.front_door_changed.connect(self._front_door_status.setStatus)

        self._slide_door_status = StatusIcon.doorIcon()
        form_layout.addRow("Sliding Door:", self._slide_door_status)
        self.slide_door_changed.connect(self._slide_door_status.setStatus)

        content_layout.addLayout(form_layout)

        self._card_widget.setContentLayout(content_layout)

        layout = QVBoxLayout()
        layout.addWidget(self._card_widget)
        self.setLayout(layout)

        hardware_model.property_changed += self._hardware_model_property_changed
        app_model.analysis.load_cell_monitor.property_changed += self._load_cell_property_changed
        app_model.analysis.audio_thrashing_monitor.property_changed += self._audio_thrashing_property_changed
        app_model.analysis.emergency_alarm_monitor.property_changed += self._alarm_monitor_property_changed

    def set_is_capture_active(self, is_editable: bool):
        self._card_widget.setEnabled(is_editable)

    def _hardware_model_property_changed(self, property_name: str, value, old_value):
        if property_name == HardwareModel.FRONT_DOOR_PROPERTY:
            self.front_door_changed.emit(value)
        elif property_name == HardwareModel.SLIDE_DOOR_PROPERTY:
            self.slide_door_changed.emit(value)

    def _load_cell_property_changed(self, name: str, new_value, old_value):
        if name == LoadCellMonitor.IS_THRASHING_DETECTED_PROPERTY:
            self.load_cell_thrashing_changed.emit(new_value)

    def _audio_thrashing_property_changed(self, name, new_value, old_value):
        if name == AudioSpectrumThrashMonitor.AUDIO_THRASHING_DETECTED_PROPERTY:
            self.audio_thrashing_changed.emit(new_value)

    def _alarm_monitor_property_changed(self,  name, value, _):
        p = EmergencyAlarmMonitor
        if name == p.USE_PRESENCE_IN_CAGE_AFTER_EXIT_TUNNEL:
            self.use_presence_in_cage_after_exit_tunnel_changed.emit(value)
        elif name == p.PRESENCE_IN_CAGE_AFTER_EXIT_TUNNEL_ENGAGED:
            self.presence_in_cage_after_exit_tunnel_changed.emit(value)
        elif name == p.USE_AUDIO_LOAD_CELL_THRASHING:
            self.use_load_cell_audio_thrash_changed.emit(value)
        elif name == p.AUDIO_LOAD_CELL_THRASHING_ENGAGED:
            self.load_cell_audio_thrash_changed.emit(value)
        elif name == p.USE_GLOBAL_MOUSE_PRESENCE:
            self.use_global_mouse_presence_changed.emit(value)
        elif name == p.GLOBAL_MOUSE_PRESENCE_ENGAGED:
            self.global_mouse_presence_changed.emit(value)
        elif name == EmergencyAlarmMonitor.AUTO_RESUME_ON_CONDITIONS_CLEARED:
            pass
