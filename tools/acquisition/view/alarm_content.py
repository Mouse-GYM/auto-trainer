from functools import partial

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QFormLayout, QSizePolicy

from autotrainer.behavior.behavior_algorithm import BehaviorAlgoProps
from autotrainer.core import LoadCellMonitor, get_verbose_logger
from autotrainer.core.analysis import EmergencyAlarmMonitor
from autotrainer.core.analysis.audio_spectrum_monitor import AudioSpectrumThrashMonitor
from autotrainer.core.analysis.global_animal_presence_monitor import GlobalAnimalPresenceMonitor
from autotrainer.core.configuration.alarm_configuration import EmergencyAlarmConfiguration
from autotrainer.pyside import CardWidget, StatusIcon
from tools.acquisition.model.app_model import AppModel
from tools.acquisition.model.hardware_model import HardwareModel

from tools.acquisition.view.content_widget import ContentWidget

logger = get_verbose_logger(__name__)


class AlarmContent(ContentWidget):
    """
    Widget to display alarm content.
    """

    # alarm monitor:
    use_load_cell_audio_thrash_changed = Signal(bool)
    load_cell_audio_thrash_changed = Signal(bool)

    use_presence_in_cage_after_exit_tunnel_changed = Signal(bool)
    presence_in_cage_after_exit_tunnel_changed = Signal(bool)

    use_external_door_changed = Signal(bool)
    external_door_status_changed = Signal(bool)

    #

    load_cell_thrashing_changed = Signal(bool, name="load_cell_thrashing_changed")
    audio_thrashing_changed = Signal(bool, name="audio_thrashing_changed")
    front_door_changed = Signal(bool, name="front_door_changed")
    slide_door_changed = Signal(bool, name="slide_door_changed")
    global_animal_presence_changed = Signal(bool)
    device_ack_timeout_changed = Signal(bool)

    def __init__(self, app_model: AppModel, hardware_model: HardwareModel):
        super().__init__()

        self._app_model = app_model
        self._hardware_model = hardware_model

        self._card_widget = CardWidget(header_background_color="red")
        self._card_widget.header.setTitle("Alarms & Detectors", color="white")

        content_layout = QVBoxLayout()
        content_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        content_layout.setContentsMargins(8, 4, 8, 4)

        form_layout = QFormLayout()
        form_layout.setHorizontalSpacing(32)

        emergency_alarm = app_model.behavior.analysis.emergency_alarm_monitor
        emergency_alarm_cfg = emergency_alarm.config

        label = QLabel("<b>Alarms</b>")
        label.setContentsMargins(0, 0, 0, 4)
        form_layout.addRow(label, None)

        def on_use_changed(do_use, *, lbl):
            lbl.setStyleSheet("" if do_use else "color: gray")

        icon = self._mouse_thrashing_status = StatusIcon.alarmIcon()
        label = self._mouse_thrashing_label = QLabel("Thrashing:")
        form_layout.addRow(label, icon)
        self.use_load_cell_audio_thrash_changed.connect(partial(on_use_changed, lbl=label))
        self.use_load_cell_audio_thrash_changed.emit(emergency_alarm_cfg.use_audio_load_cell_thrash)
        self.load_cell_audio_thrash_changed.connect(icon.setStatus)

        icon = self._in_cage_after_tunnel_status = StatusIcon.alarmIcon()
        label = self._in_cage_after_tunnel_label = QLabel("Mouse Missing:")
        form_layout.addRow(label, icon)
        self.use_presence_in_cage_after_exit_tunnel_changed.connect(partial(on_use_changed, lbl=label))
        self.use_presence_in_cage_after_exit_tunnel_changed.emit(emergency_alarm_cfg.use_presence_missing_after_exit_tunnel)
        self.presence_in_cage_after_exit_tunnel_changed.connect(icon.setStatus)

        icon = self._external_door_status = StatusIcon.alarmIcon()
        label = self._external_door_label = QLabel("External doors:")
        form_layout.addRow(label, icon)
        self.use_external_door_changed.connect(partial(on_use_changed, lbl=label))
        self.use_external_door_changed.emit(emergency_alarm_cfg.use_external_doors_open)
        self.external_door_status_changed.connect(icon.setStatus)

        #

        label = QLabel("<b>Detectors</b>")
        label.setContentsMargins(0, 8, 0, 4)
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

        if GlobalAnimalPresenceMonitor.feature_enabled:
            icon = self._animal_missing_status = StatusIcon.alarmIcon()
            label = self._animal_missing_label = QLabel("Animal Immobile:")
            form_layout.addRow(label, icon)
            self.global_animal_presence_changed.connect(icon.setStatus)

        icon = self._device_ack_timeout_status = StatusIcon.alarmIcon()
        form_layout.addRow("Device Ack Timeout:", icon)
        self.device_ack_timeout_changed.connect(icon.setStatus)

        content_layout.addLayout(form_layout)

        self._card_widget.setContentLayout(content_layout)
        self._card_widget.setContentsMargins(0, 0, 0, 0)
        self._card_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout()
        layout.addWidget(self._card_widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.setLayout(layout)

        hardware_model.property_changed += self._hardware_model_property_changed
        #
        analysis = app_model.analysis
        analysis.load_cell_monitor.property_changed += self._load_cell_property_changed
        analysis.audio_thrashing_monitor.property_changed += self._audio_thrashing_property_changed
        analysis.emergency_alarm_monitor.property_changed += self._alarm_monitor_property_changed
        analysis.global_animal_presence_monitor.property_changed += self._global_animal_presence_property_changed
        analysis.external_doors_monitor.property_changed += self._ext_door_property_changed

    def set_is_capture_active(self, is_editable: bool):
        self._card_widget.setEnabled(is_editable)

    def _hardware_model_property_changed(self, name: str, value, _):
        if name == HardwareModel.FRONT_DOOR_PROPERTY:
            self.front_door_changed.emit(value)
        elif name == HardwareModel.SLIDE_DOOR_PROPERTY:
            self.slide_door_changed.emit(value)
        elif name == HardwareModel.DEVICE_ACK_TIMEOUT_ENGAGED:
            self.device_ack_timeout_changed.emit(value)

    def _load_cell_property_changed(self, name: str, new_value, _):
        if name == LoadCellMonitor.IS_THRASHING_DETECTED_PROPERTY:
            self.load_cell_thrashing_changed.emit(new_value)

    def _audio_thrashing_property_changed(self, name, new_value, _):
        if name == AudioSpectrumThrashMonitor.AUDIO_THRASHING_DETECTED_PROPERTY:
            self.audio_thrashing_changed.emit(new_value)

    def _alarm_monitor_property_changed(self,  name, value, _):
        p = EmergencyAlarmMonitor
        if name == p.CONFIG:
            assert isinstance(value, EmergencyAlarmConfiguration)
            self.use_presence_in_cage_after_exit_tunnel_changed.emit(value.use_presence_missing_after_exit_tunnel)
            self.use_load_cell_audio_thrash_changed.emit(value.use_audio_load_cell_thrash)
            self.use_external_door_changed.emit(value.use_external_doors_open)
        elif name == p.PRESENCE_IN_CAGE_AFTER_EXIT_TUNNEL_ENGAGED:
            self.presence_in_cage_after_exit_tunnel_changed.emit(value)
        elif name == p.AUDIO_LOAD_CELL_THRASHING_ENGAGED:
            self.load_cell_audio_thrash_changed.emit(value)

    def _global_animal_presence_property_changed(self, name, value, _):
        if name == "is_engaged":
            self.global_animal_presence_changed.emit(value)

    def _ext_door_property_changed(self, name, value, _):
        if name == "is_engaged":
            self.external_door_status_changed.emit(value)
