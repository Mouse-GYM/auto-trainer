import dataclasses
import enum
from datetime import datetime
from typing import Optional, Callable, List

from autotrainer.api import ApiEmergencyStopReason, ApiEmergencyResumeReason, ApiAlarmKind
from autotrainer.api.event import build_event, EmergencyStopContext, EmergencyResumeContext

from autotrainer.api import ApiEventKind

from autotrainer.core import (ObservableObject, ProjectInfo, SensorAnalysis, BehaviorConfiguration,
                              SystemMessageHandler)
from autotrainer.core.analysis.alarm_monitor import EmergencyReason, emergency_reason_2_api_alarm_kind
from autotrainer.core.analysis.detector import GroupBaseDetector
from autotrainer.core.configuration.alarm_detector import AlarmDetectorConfig
from autotrainer.core.configuration.detector import GroupSubDetectorConfig
from autotrainer.core.event import post_api_event_content, post_api_event
from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.observable_object import EventHandler
from autotrainer.core.video_detection import PresenceDetectionAttrs

from autotrainer.behavior import SystemMachine, InferenceProtocol, BehaviorAlgorithm, SystemState, IntertrialState
from autotrainer.behavior.behavior_algorithm import BehaviorAlgoStatus

from tools.acquisition.model.hardware_model import HardwareModel

from autotrainer.core.project import ProjectDependentProtocol
logger = get_verbose_logger(__name__)


class EmergencyControlSource(str, enum.Enum):

    USER_BUTTON = "user-button"
    RPC_SERVICE = "RpcService"
    OTHER = "other"  # any combination of emergency monitor possible alarms

    @classmethod
    def _missing_(cls, value):
        return cls.OTHER  # Fallback choice for invalid lookups

    default = _missing_  # forward compatibility

    def is_admin_source(self) -> bool:
        return self is self.USER_BUTTON or self is self.RPC_SERVICE


class BehaviorModel(ObservableObject, ProjectDependentProtocol):
    """
    Encapsulation of the Behavior Module (autotrainer-behavior) for the application layer.  This model class manages
    aspects of the behavior system that are specific to the application.  General behavior functionality should be
    located in the module.

    Emergency stopped and resumed are defined as dedicated events due to their application-wide interest and possible
    subscription.  Anything that triggers an emergency stop/resume should pass through the `emergency_stop` and
    `emergency_resume` methods to ensure
    """

    # events type hint
    emergency_stopped: EventHandler[Callable[[str], None]]
    emergency_resumed: EventHandler[Callable[[str], None]]

    def __init__(
        self,
        msg_handler: SystemMessageHandler,
        analysis: SensorAnalysis,
        hardware_model: HardwareModel,
        inference: InferenceProtocol,
        *,
        topcam_presence: Optional[PresenceDetectionAttrs] = None,
        system_machine: Optional[SystemMachine] = None,
    ):
        super().__init__(("emergency_stopped", "emergency_resumed"))

        self._project = ProjectInfo.get_null_project()

        self._analysis = analysis
        if system_machine is None:
            system_machine = SystemMachine(
                msg_handler=msg_handler,
                analysis=analysis,
                tunnel_device=hardware_model,
                pellet_device=hardware_model,
                inference=inference,
                topcam_presence=topcam_presence,
            )
        self._system_machine: SystemMachine = system_machine
        self._hardware_model = hardware_model
        #
        self._source_emergency: Optional[str] = None
        self._emergency_engaged_alarms: List[ApiAlarmKind] = []
        #
        analysis.emergency_alarm_monitor.property_changed += self._alarm_monitor_property_changed

    @BehaviorAlgorithm.relay_func(wait=False)
    def _alarm_monitor_property_changed(self, name, value, old_value):
        # logger.debug("alarm-mon: %s : %s -> %s", name, old_value, value)
        alarm_mon = self._analysis.emergency_alarm_monitor
        if name == alarm_mon.IS_ENGAGED:
            algo = self._system_machine.algorithm
            algo_status = algo.status
            if not value:
                # nothing engaged, all ok
                if self._source_emergency is not None:
                    self.emergency_resume(
                        "alarm-monitor-resumed",
                        reason_code=ApiEmergencyResumeReason.alarm_monitor_resume,
                        resumed_alarms=list(self._emergency_engaged_alarms),
                    )
            else:
                if algo_status is BehaviorAlgoStatus.ANIMAL_IN_TRAINING:
                    valid_reasons = list(EmergencyReason)
                elif algo_status is BehaviorAlgoStatus.ANIMAL_IN_DEVICE:
                    valid_reasons = {  # == all but mouse thrashing, should we include it ?
                        EmergencyReason.DOORS_OPEN,
                        EmergencyReason.GLOBAL_ANIMAL_PRESENCE,
                        EmergencyReason.DEVICE_COMM_ERROR,
                        EmergencyReason.SYSTEM_FAULT,
                        EmergencyReason.SYSTEM_MAINTENANCE,
                    }
                else:  # idle or acquiring (== running)
                    valid_reasons = {
                        EmergencyReason.SYSTEM_FAULT,
                        EmergencyReason.SYSTEM_MAINTENANCE,
                        EmergencyReason.DEVICE_COMM_ERROR,
                    }
                #
                engaged_reasons = alarm_mon.engaged_reasons
                filtered_valid_reasons = list(filter(lambda v: v in valid_reasons, engaged_reasons))
                logger.verbose("filtered_reasons=%s", filtered_valid_reasons)
                if len(filtered_valid_reasons) > 0:
                    # at least one possible valid reason engaged
                    reasons = " ".join(
                        reason.name if isinstance(reason, enum.Enum) else reason
                        for reason in engaged_reasons)
                    self.emergency_stop(f"alarm-monitor: {reasons}", reason_code=ApiEmergencyStopReason.alarm_monitor)
                else:
                    logger.verbose("skipping emergency stop ; algo status=%s reasons=%s",
                                   algo_status, engaged_reasons)
                    self.emergency_resume("alarm-monitor-no-valid-condition-remaining",
                                          reason_code=ApiEmergencyResumeReason.alarm_monitor_status_change)

    @property
    def analysis(self) -> SensorAnalysis:
        return self._analysis

    @property
    def project(self) -> ProjectInfo:
        return self._project

    @project.setter
    def project(self, value: ProjectInfo) -> None:
        self._project = value
        self._system_machine.project = value
        # self._machine.project = value  # instead of having to do it in on_prepare_capture()

    @property
    def system_machine(self) -> SystemMachine:
        return self._system_machine

    @property
    def algorithm(self) -> BehaviorAlgorithm:
        return self._system_machine.algorithm

    def load_configuration(self, config: BehaviorConfiguration):
        system_m = self._system_machine
        system_m.shift_xyz_handler.set_config(config.shift_xyz_handler)
        system_m.algorithm.load_configuration(config)
        analysis = self._analysis
        analysis.headbar_pressure_monitor.config = config.headbar_pressure
        analysis.load_cell_monitor.load_configuration(config.load_cell)
        analysis.load_cell_tare_monitor.config = config.auto_tare
        analysis.audio_thrashing_monitor.config = config.audio
        analysis.auto_tunnel_sweep_monitor.config = config.auto_tunnel_sweep
        analysis.auto_tunnel_sweep_monitor.animal_sleep_window = config.animal_sleep_window
        analysis.autoclamp_evasion_detector.config = config.autoclamp_evasion_detector
        #
        alarm_cfg = config.emergency_alarm
        analysis.emergency_alarm_monitor.config = alarm_cfg
        # also need to set explicitly the different alarm configs on their alarm instance:
        analysis.animal_evasion_alarm.config = alarm_cfg.animal_evasion
        analysis.animal_thrashing_alarm.config = alarm_cfg.animal_thrashing
        analysis.system_maintenance_alarm.config = alarm_cfg.system_maintenance
        analysis.presence_in_cage_alarm.config = alarm_cfg.presence_in_cage
        analysis.global_animal_presence_alarm.config = alarm_cfg.global_animal_presence
        analysis.device_comm_alarm.config = alarm_cfg.device_comm_error
        analysis.external_doors_alarm.config = alarm_cfg.external_doors
        # same with fault config sub-elements:
        fault_cfg = alarm_cfg.system_fault
        analysis.system_fault_alarm.config = fault_cfg
        analysis.free_disk_space_detector.config = fault_cfg.free_disk_space
        analysis.boards_hardware_reset_detector.config = fault_cfg.boards_hardware_reset
        # NB: watchdog config is currently at system-config top level.
        # so that they emit the CONFIG changed event.

    def save_configuration(self) -> BehaviorConfiguration:
        algo = self._system_machine.algorithm

        assigned = {}
        created = False
        class ConfigWrap(BehaviorConfiguration):
            def __setattr__(self, key, value):
                if created:
                    assigned[key] = value

        config = ConfigWrap()
        created = True

        analysis = self._analysis

        # NB: monitors/detectors configuration:
        config.load_cell = analysis.load_cell_monitor.save_configuration()
        config.auto_tare = analysis.load_cell_tare_monitor.save_configuration()
        config.headbar_pressure = analysis.headbar_pressure_monitor.config
        config.audio = analysis.audio_thrashing_monitor.config
        config.auto_tunnel_sweep = analysis.auto_tunnel_sweep_monitor.config
        config.animal_sleep_window = algo.active_config.animal_sleep_window
        #
        alarm_cfg = config.emergency_alarm = analysis.emergency_alarm_monitor.config
        alarm_cfg.external_doors = analysis.external_doors_alarm.config
        alarm_cfg.global_animal_presence = analysis.global_animal_presence_alarm.config
        alarm_cfg.device_comm_error = analysis.device_comm_alarm.config
        alarm_cfg.presence_in_cage = analysis.presence_in_cage_alarm.config
        alarm_cfg.animal_thrashing = analysis.animal_thrashing_alarm.config
        #
        fault_cfg = alarm_cfg.system_fault = analysis.system_fault_alarm.config
        fault_cfg.free_disk_space = analysis.free_disk_space_detector.config
        fault_cfg.boards_hardware_reset = analysis.boards_hardware_reset_detector.config
        #
        alarm_cfg.system_maintenance = analysis.system_maintenance_alarm.config
        alarm_cfg.animal_evasion = analysis.animal_evasion_alarm.config

        top_cam = algo.top_camera_presence_detection
        config.topcam_presence_detection = None if top_cam is None else top_cam.to_config()
        config.autoclamp_evasion_detector = analysis.autoclamp_evasion_detector.config

        config = dataclasses.replace(algo.active_config, **assigned)
        orig_fields = {f.name for f in dataclasses.fields(config)}
        missed = orig_fields - set(assigned)
        if len(missed) > 0:
            logger.debug("Fields %s not assigned / missed during save_config", missed)

        return config

    def on_prepare_capture(self):
        self._system_machine.project = self._project
        self._system_machine.state = SystemState.cage  # forced,
        self._system_machine.intertrial.state = IntertrialState.idle
        # if acquisition is/was stopped during an intertrial analysis,
        # then it's left on intertrial+(segmentation | detection) state..
        # which further prevent everything after.
        # todo: try have intertrial stop "normally" too

    def use_current_head_magnet_position_as_baseline(self):
        head_magnet_intensity = self._hardware_model.head_magnet_intensity
        if head_magnet_intensity is not None:
            algo = self._system_machine.algorithm
            algo.baseline_intensity = head_magnet_intensity
            # NB: behavior_algo.baseline_intensity is currently not connected to config value,
            # but we want save it here:
            algo.active_config.head_clamp.baseline_intensity = head_magnet_intensity
            post_api_event_content(ApiEventKind.headfixBaselineChanged,
                                   data=dict(baseline=head_magnet_intensity))

    @property
    def source_emergency(self) -> Optional[str]:
        return self._source_emergency

    @BehaviorAlgorithm.relay_func()
    def emergency_stop(self, source: str, *, reason_code: ApiEmergencyStopReason=ApiEmergencyStopReason.unknown):
        algo = self._system_machine.algorithm
        logger.info("emergency_stop called: %s", source)
        if algo.algo_paused and source == self._source_emergency:
            # double emergency_stop ?
            return
        current = EmergencyControlSource(self._source_emergency)
        if current is not None and current.is_admin_source():
            logger.verbose("ignoring stop emergency from %s given current one (%s) is admin",
                           source, current)
            return
        api_alarm_kinds = []
        all_reasons = tuple(EmergencyReason)
        for r in self._analysis.emergency_alarm_monitor.engaged_reasons:
            if isinstance(r, EmergencyReason) or r in all_reasons:
                r = EmergencyReason(r)
                api_alarm_kinds.append(emergency_reason_2_api_alarm_kind(r))
        self._emergency_engaged_alarms = api_alarm_kinds
        #
        post_api_event(build_event(
            ApiEventKind.emergencyStop,
            EmergencyStopContext(reason=source,
                                 reason_code=reason_code,
                                 active_alarms=api_alarm_kinds)))
        self._source_emergency = source
        algo.algo_paused = True
        self.emergency_stopped(source)

    @BehaviorAlgorithm.relay_func()
    def emergency_resume(
        self,
        source: str,
        *,
        reason_code: ApiEmergencyResumeReason=ApiEmergencyResumeReason.unknown,
        resumed_alarms: Optional[List[ApiAlarmKind]] = None,
    ):
        algo = self._system_machine.algorithm
        logger.info("emergency_resume called: %s - current=%s", source, algo.algo_paused)
        if resumed_alarms is None:
            resumed_alarms = []
        if not algo.algo_paused:  # should be same than self._source_emergency is None
            logger.debug("algo not paused, skipping emergency_resume from %s", source)
            return
        control_src = EmergencyControlSource(source)
        current = EmergencyControlSource(self._source_emergency)
        if current is not None and current.is_admin_source() and not control_src.is_admin_source():
            logger.verbose("Refusing resume from emergency %s given was set by %s",
                          source, current)
            return
        post_api_event(build_event(ApiEventKind.emergencyResume,
            EmergencyResumeContext(
                reason=source, reason_code=reason_code, resumed_alarms=resumed_alarms)))
        self._source_emergency = None
        if reason_code == ApiEmergencyResumeReason.alarm_monitor_resume:
            self._emergency_engaged_alarms = []
        self._source_emergency = None
        algo.algo_paused = False
        self.emergency_resumed(source)

    def get_led_color(self, *, now: Optional[datetime]=None):
        if now is None:
            now = datetime.now()
        algo = self._system_machine.algorithm
        alarm_mon = self._analysis.emergency_alarm_monitor
        if alarm_mon.is_engaged or algo.algo_paused:
            color = (100, 0, 0)  # red
        else:
            def _is_warn(det):
                det_cfg = det.config
                return (
                    det.is_engaged
                    and (not isinstance(det_cfg, GroupSubDetectorConfig) or det_cfg.use)
                    and (isinstance(det.config, AlarmDetectorConfig) and not det.config.is_emergency_condition)
                )
            is_warn = any(filter(_is_warn, alarm_mon.sub_detectors.values()))
            color = (100, 100, 0) if is_warn else (0, 100, 0)
            # yellow or green
            cur_time = now.time()
            in_ignore_window = algo.active_config.animal_sleep_window.is_time_present(cur_time)
            if in_ignore_window:
                color = (0, 0, 0)
        return color
