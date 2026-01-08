from functools import partial

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import QLabel, QVBoxLayout, QFormLayout, QSizePolicy, QScrollArea, QWidget, QHBoxLayout, QLayout

from autotrainer.behavior.behavior_algorithm import BehaviorAlgoProps
from autotrainer.core import LoadCellMonitor, get_verbose_logger
from autotrainer.core.analysis import EmergencyAlarmMonitor
from autotrainer.core.analysis.audio_spectrum_monitor import AudioSpectrumThrashMonitor
from autotrainer.core.analysis.global_animal_presence_monitor import GlobalAnimalPresenceMonitor
from autotrainer.core.configuration.alarm_configuration import EmergencyAlarmConfiguration
from autotrainer.pyside import CardWidget, StatusIcon
from autotrainer.pyside.content_widget import ContentWidget

from tools.acquisition.model.app_model import AppModel
from tools.acquisition.model.hardware_model import HardwareModel

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
        # self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._app_model = app_model
        self._hardware_model = hardware_model

        card = self._card_widget = CardWidget(header_background_color="red")
        card.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        card.header.setTitle("Alarms & Detectors", color="white")

        content_layout = QHBoxLayout()
        content_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        content_layout.setSpacing(16)
        content_layout.setContentsMargins(8, 4, 8, 4)

        form_layout_alarms = QFormLayout()
        form_layout_alarms.setHorizontalSpacing(8)
        form_layout_alarms.setVerticalSpacing(4)
        form_layout_alarms.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)

        emergency_alarm = app_model.behavior.analysis.emergency_alarm_monitor
        emergency_alarm_cfg = emergency_alarm.config

        label = QLabel("<b>Alarms</b>")
        label.setContentsMargins(0, 0, 0, 4)
        form_layout_alarms.addRow(label, None)

        def make_icon(size: int = 18, off_color: str = "black", name: str = "NA"):
            ico = StatusIcon(on_icon='fa5s.bell', off_icon='fa5.bell', on_color='red', off_color=off_color, size=size, name=name)
            return ico

        make_alarm_icon = lambda name: StatusIcon(
            on_icon='fa5s.bell',
            on_disabled_icon='fa5.bell',
            off_icon='fa5.bell',
            off_disabled_icon='fa5.bell',
            on_color='red',
            on_disabled_color='red',
            off_color='black',
            off_disabled_color='gray',
            name=name,
        )
        make_detector_icon = partial(make_icon, off_color="black")

        def make_label(txt: str) -> QLabel:
            lbl = QLabel(txt)
            palette = lbl.palette()
            palette.setColor(QPalette.ColorGroup.Active, QPalette.ColorRole.WindowText, QColor("black"))
            palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor("gray"))
            # NB: Inactive != Disabled, later has to be used. Same for WindowText vs Text roles.
            lbl.setPalette(palette)
            return lbl

        icon = self._mouse_thrashing_status = make_alarm_icon("alarm-thrashing")
        label = self._mouse_thrashing_label = make_label("Thrashing:")
        form_layout_alarms.addRow(label, icon)
        self.use_load_cell_audio_thrash_changed.connect(label.setEnabled)
        self.use_load_cell_audio_thrash_changed.connect(icon.setInUse)
        self.use_load_cell_audio_thrash_changed.emit(emergency_alarm_cfg.use_audio_load_cell_thrash)
        self.load_cell_audio_thrash_changed.connect(icon.setStatus)

        icon = self._in_cage_after_tunnel_status = make_alarm_icon("alarm-missing")
        label = self._in_cage_after_tunnel_label = make_label("Mouse Missing:")
        form_layout_alarms.addRow(label, icon)
        self.use_presence_in_cage_after_exit_tunnel_changed.connect(label.setEnabled)
        self.use_presence_in_cage_after_exit_tunnel_changed.connect(icon.setInUse)
        self.use_presence_in_cage_after_exit_tunnel_changed.emit(emergency_alarm_cfg.use_presence_missing_after_exit_tunnel)
        self.presence_in_cage_after_exit_tunnel_changed.connect(icon.setStatus)

        icon = self._external_door_status = make_alarm_icon("alarm-ext-doors")
        label = self._external_door_label = make_label("External doors:")
        form_layout_alarms.addRow(label, icon)
        self.use_external_door_changed.connect(label.setEnabled)
        self.use_external_door_changed.connect(icon.setInUse)
        self.use_external_door_changed.emit(emergency_alarm_cfg.use_external_doors_open)
        self.external_door_status_changed.connect(icon.setStatus)

        #

        form_layout_detectors = QFormLayout()
        form_layout_detectors.setHorizontalSpacing(16)
        form_layout_detectors.setVerticalSpacing(4)
        form_layout_detectors.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)

        label = QLabel("<b>Detectors</b>")
        label.setContentsMargins(0, 0, 0, 4)
        form_layout_detectors.addRow(label, None)

        self._load_cell_thrash_status = make_detector_icon(name="det-load-cell-thrash")
        form_layout_detectors.addRow("Load Cell Thrash:", self._load_cell_thrash_status)
        self.load_cell_thrashing_changed.connect(self._load_cell_thrash_status.setStatus)

        self._audio_spectrum_status = make_detector_icon(name="det-audio")
        form_layout_detectors.addRow("Audio:", self._audio_spectrum_status)
        self.audio_thrashing_changed.connect(self._audio_spectrum_status.setStatus)

        self._front_door_status = StatusIcon.doorIcon(name="det-front-door")
        form_layout_detectors.addRow("Front Door:", self._front_door_status)
        self.front_door_changed.connect(self._front_door_status.setStatus)

        self._slide_door_status = StatusIcon.doorIcon(name="det-slide-door")
        form_layout_detectors.addRow("Sliding Door:", self._slide_door_status)
        self.slide_door_changed.connect(self._slide_door_status.setStatus)

        if GlobalAnimalPresenceMonitor.feature_enabled:
            icon = self._animal_missing_status = make_detector_icon(name="det-immobile")
            label = self._animal_missing_label = QLabel("Animal Immobile:")
            form_layout_detectors.addRow(label, icon)
            self.global_animal_presence_changed.connect(icon.setStatus)

        icon = self._device_ack_timeout_status = make_detector_icon(name="det-device-ack")
        form_layout_detectors.addRow("Device Ack Timeout:", icon)
        self.device_ack_timeout_changed.connect(icon.setStatus)

        icon = self._pellet_misplaced_status = make_detector_icon(name="pellet-misplaced")
        form_layout_detectors.addRow("Pellet Misplaced:", icon)

        content_layout.addLayout(form_layout_alarms)
        content_layout.addLayout(form_layout_detectors)

        content_widget = QWidget()
        content_widget.setLayout(content_layout)
        # content_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        card.setContentWidget(content_widget)
        card.setContentsMargins(0, 0, 0, 0)
        # card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout()
        # layout.setSizeConstraint(QHBoxLayout.SizeConstraint.SetMinimumSize)
        layout.addWidget(card)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.setLayout(layout)

        hardware_model.property_changed += self._hardware_model_property_changed
        #
        analysis = app_model.analysis
        analysis.load_cell_monitor.property_changed += self._load_cell_property_changed
        analysis.audio_thrashing_monitor.property_changed += self._audio_thrashing_property_changed
        analysis.global_animal_presence_monitor.property_changed += self._global_animal_presence_property_changed
        # emergency alarm controls 3 sub-alarms:
        analysis.emergency_alarm_monitor.property_changed += self._alarm_monitor_property_changed
        # analysis.external_doors_monitor.property_changed += self._ext_door_property_changed
        analysis.pellet_misplaced_monitor.property_changed += self._pellet_misplaced_property_changed

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

    def _alarm_monitor_property_changed(self, name, value, old_value):
        p = EmergencyAlarmMonitor
        logger.debug("got %s -> %s (was %s)", name, value, old_value)
        alarm_monitor = self._app_model.analysis.emergency_alarm_monitor
        is_pause_emergency = self._app_model.behavior.algorithm.algo_paused
        cfg = alarm_monitor.config
        if name == p.CONFIG:
            assert isinstance(value, EmergencyAlarmConfiguration)
            self.use_load_cell_audio_thrash_changed.emit(value.use_audio_load_cell_thrash)
            self.use_presence_in_cage_after_exit_tunnel_changed.emit(value.use_presence_missing_after_exit_tunnel)
            self.use_external_door_changed.emit(value.use_external_doors_open)

        elif name == p.IS_ENGAGED:
            if not value:
                mon = alarm_monitor
                changed = self._alarm_monitor_property_changed
                changed(p.PRESENCE_IN_CAGE_AFTER_EXIT_TUNNEL_ENGAGED, mon.presence_in_cage_after_exit_tunnel_engaged, None)
                changed(p.AUDIO_LOAD_CELL_THRASHING_ENGAGED, mon.audio_load_cell_thrashing_engaged, None)
                changed(p.EXT_DOORS_OPEN_ENGAGED, mon.ext_doors_open_engaged, None)

        elif name == p.PRESENCE_IN_CAGE_AFTER_EXIT_TUNNEL_ENGAGED:
            if not value and is_pause_emergency and not cfg.auto_resume_on_presence_seen_after_exit_tunnel:
                return
            self.presence_in_cage_after_exit_tunnel_changed.emit(value)

        elif name == p.AUDIO_LOAD_CELL_THRASHING_ENGAGED:
            if not value and is_pause_emergency and not cfg.auto_resume_on_audio_load_cell_thrash_resume:
                return
            self.load_cell_audio_thrash_changed.emit(value)

        elif name == p.EXT_DOORS_OPEN_ENGAGED:
            if not value and is_pause_emergency and not cfg.auto_resume_on_external_doors_close:
                return
            self.external_door_status_changed.emit(value)

    def _global_animal_presence_property_changed(self, name, value, _):
        if name == "is_engaged":
            self.global_animal_presence_changed.emit(value)

    def _pellet_misplaced_property_changed(self, name, value, _):
        if name == "is_engaged":
            self._pellet_misplaced_status.setStatus(value)
