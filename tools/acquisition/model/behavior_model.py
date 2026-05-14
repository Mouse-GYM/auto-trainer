import copy
import dataclasses
import multiprocessing
from typing import Optional, Callable

from autotrainer.behavior import SystemMachine, InferenceProtocol, BehaviorAlgorithm, SystemState, IntersessionState
from autotrainer.behavior.behavior_algorithm import BehaviorAlgoProps, BehaviorAlgoStatus
from autotrainer.behavior.pellet_shift import ShiftXYZBufferHandler
from autotrainer.behavior.state_machine import StateMachine
from autotrainer.core import (ObservableObject, ProjectInfo, SensorAnalysis, BehaviorConfiguration,
                              SystemMessageHandler, EventManager, ApiEventKind)
from autotrainer.core.analysis import EmergencyAlarmMonitor
from autotrainer.core.analysis.alarm_monitor import EmergencyReason, emergency_reason_2_api_alarm_kind
from autotrainer.core.configuration.behavior_configuration import ShiftXYZHandlerConfig
from autotrainer.core.event import post_api_event_content
from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.video_detection import PresenceDetectionAttrs
from tools.acquisition.model.hardware_model import HardwareModel

from autotrainer.core.project import ProjectDependentProtocol

logger = get_verbose_logger(__name__)


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
    emergency_stopped: Callable[[str], None]
    emergency_resumed: Callable[[str], None]

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

        self._project: Optional[ProjectInfo] = None

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
        #
        # system_machine.pellet.events.state_changed += lambda old_val, new_val: self._on_property_changed(
        #     f"pellet.{StateMachine.Properties.STATE_PROPERTY}", new_val, old_val)
        # actually unused event (pellet.state)

        analysis.emergency_alarm_monitor.property_changed += self._alarm_monitor_property_changed

    @BehaviorAlgorithm.relay_func(wait=False)
    def _alarm_monitor_property_changed(self, name, value, old_value):
        # logger.debug("alarm-mon: %s : %s -> %s", name, old_value, value)
        alarm_mon = self._analysis.emergency_alarm_monitor
        # if alarm_mon.is_engaged_prop(name):
        if alarm_mon.IS_ENGAGED:  # only need check main one,
            # it's force-republished whenever any config also changed,
            # so that we can evaluate the is_stop_condition here:
            algo = self._system_machine.algorithm
            algo_status = algo.status
            alarm_cfg = alarm_mon.config
            if not alarm_mon.is_engaged:
                # nothing engaged, all ok
                if algo.algo_paused:
                    self.emergency_resume("alarm-monitor-resumed")
            else:
                if algo_status is BehaviorAlgoStatus.ANIMAL_IN_TRAINING:
                    valid_reasons = list(EmergencyReason)
                elif algo_status is BehaviorAlgoStatus.ANIMAL_IN_DEVICE:
                    valid_reasons = {
                        EmergencyReason.DOORS_OPEN,
                        EmergencyReason.IN_CAGE_AFTER_EXIT_TUNNEL,
                        EmergencyReason.GLOBAL_ANIMAL_PRESENCE,
                        EmergencyReason.SYSTEM_FAULT,
                        EmergencyReason.SYSTEM_MAINTENANCE,
                    }
                else:  # idle or acquiring (== running)
                    valid_reasons = {
                        EmergencyReason.SYSTEM_FAULT,
                        EmergencyReason.SYSTEM_MAINTENANCE,
                    }
                #
                map_reason_to_is_stop_condition = {
                    EmergencyReason.GLOBAL_ANIMAL_PRESENCE: alarm_cfg.global_animal_presence_is_emergency_stop_condition,
                    EmergencyReason.DEVICE_COMM_ERROR: alarm_cfg.device_comm_error_is_emergency_stop_condition,
                    EmergencyReason.SYSTEM_MAINTENANCE: alarm_cfg.system_maintenance_is_emergency_stop_condition,
                    EmergencyReason.SYSTEM_FAULT: alarm_cfg.system_fault_is_emergency_stop_condition,
                    EmergencyReason.MOUSE_THRASHING: alarm_cfg.audio_load_cell_is_emergency_stop_condition,
                    EmergencyReason.IN_CAGE_AFTER_EXIT_TUNNEL: alarm_cfg.presence_missing_is_emergency_stop_condition,
                    EmergencyReason.DOORS_OPEN: alarm_cfg.external_doors_open_is_emergency_stop_condition,
                }
                reasons = alarm_mon.engaged_reasons
                is_stop_condition_reasons = []
                for reason in reasons:
                    if map_reason_to_is_stop_condition[reason]:
                        is_stop_condition_reasons.append(reason)
                filtered_valid_reasons = list(filter(lambda v: v in valid_reasons, is_stop_condition_reasons))
                logger.verbose(
                    "filtered_reasons=%s is_stop_condition_reasons=%s map=%s",
                    filtered_valid_reasons, is_stop_condition_reasons, map_reason_to_is_stop_condition,
                )
                if len(filtered_valid_reasons) > 0:
                    # at least one possible valid reason engaged with is_stop_condition=True
                    reasons = " ".join(reason.name for reason in is_stop_condition_reasons)
                    self.emergency_stop(f"alarm-monitor: {reasons}")
                else:
                    logger.verbose("skipping emergency stop ; algo status=%s reasons=%s",
                                   algo_status, reasons)
                    if len(is_stop_condition_reasons) == 0 and algo.algo_paused:
                        self.emergency_resume("alarm-monitor-no-is-stop-condition-remaining")

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
        analysis.headbar_pressure_monitor.load_configuration(config.headbar_pressure)
        analysis.load_cell_monitor.load_configuration(config.load_cell)
        analysis.load_cell_tare_monitor.load_configuration(config.auto_tare)
        analysis.audio_thrashing_monitor.config = config.audio
        analysis.emergency_alarm_monitor.config = config.emergency_alarm
        analysis.global_animal_presence_monitor.config = config.global_animal_presence
        analysis.external_doors_monitor.config = config.external_doors
        analysis.auto_tunnel_sweep_monitor.config = config.auto_tunnel_sweep
        analysis.system_maintenance_monitor.config = config.system_maintenance
        analysis.system_fault_monitor.config = config.system_fault

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
        config.headbar_pressure = analysis.headbar_pressure_monitor.save_configuration()
        config.audio = analysis.audio_thrashing_monitor.config
        config.emergency_alarm = analysis.emergency_alarm_monitor.config
        top_cam = algo.top_camera_presence_detection
        config.topcam_presence_detection = None if top_cam is None else top_cam.to_config()
        config.global_animal_presence = analysis.global_animal_presence_monitor.config
        config.external_doors = analysis.external_doors_monitor.config
        config.auto_tunnel_sweep = analysis.auto_tunnel_sweep_monitor.config
        config.system_maintenance = analysis.system_maintenance_monitor.config
        config.system_fault = analysis.system_fault_monitor.config

        config = dataclasses.replace(algo.active_config, **assigned)
        orig_fields = {f.name for f in dataclasses.fields(config)}
        missed = orig_fields - set(assigned)
        if len(missed) > 0:
            logger.debug("Fields %s not assigned / missed during save_config", missed)

        return config

    def on_prepare_capture(self):
        self._system_machine.project = self._project
        self._system_machine.state = SystemState.cage  # forced,
        self._system_machine.intersession.state = IntersessionState.idle
        # if acquisition is/was stopped during an intersession analysis,
        # then it's left on intersession+(segmentation | detection) state..
        # which further prevent everything after.
        # todo: try have intersession stop "normally" too

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
    def emergency_stop(self, source: str):
        algo = self._system_machine.algorithm
        logger.info("emergency_stop called: %s - current=%s", source, algo.algo_paused)
        if algo.algo_paused and source == self._source_emergency:
            return
        algo.algo_paused = True
        self._source_emergency = source
        api_alarm_kinds = list(map(emergency_reason_2_api_alarm_kind,
                                   self._analysis.emergency_alarm_monitor.engaged_reasons))
        post_api_event_content(
            ApiEventKind.emergencyStop,
            data=dict(reason=source, active_alarms=api_alarm_kinds))
        self.emergency_stopped(source)

    @BehaviorAlgorithm.relay_func()
    def emergency_resume(self, source: str):
        algo = self._system_machine.algorithm
        logger.info("emergency_resume called: %s - current=%s", source, algo.algo_paused)
        if not algo.algo_paused:
            return
        if self._source_emergency == "user-button" and source != "user-button":
            logger.notice("Refusing resume from emergency given was set by user ; resume source=%s", source)
            return
        algo.algo_paused = False
        self._source_emergency = None
        # restart full analysis so that monitors/detectors counters/context are reset, as if app was just started:
        self._analysis.restart()
        post_api_event_content(ApiEventKind.emergencyResume, data=dict(reason=source))
        self.emergency_resumed(source)
