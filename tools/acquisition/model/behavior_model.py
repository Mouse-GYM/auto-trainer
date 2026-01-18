import copy
import dataclasses
import multiprocessing
from typing import Optional, Callable

from autotrainer.behavior import SystemMachine, InferenceProtocol, BehaviorAlgorithm, SystemState, IntersessionState
from autotrainer.behavior.behavior_algorithm import BehaviorAlgoProps
from autotrainer.behavior.state_machine import StateMachine
from autotrainer.core import (ObservableObject, ProjectInfo, SensorAnalysis, BehaviorConfiguration,
                              SystemMessageHandler, EventManager, ApiEventKind)
from autotrainer.core.analysis import EmergencyAlarmMonitor
from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.video_detection import PresenceDetectionAttrs
from tools.acquisition.model.hardware_model import HardwareModel

from autotrainer.core.project import ProjectDependentProtol

logger = get_verbose_logger(__name__)


class BehaviorModel(ObservableObject, ProjectDependentProtol):
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

        self._analysis = analysis

        system_machine = self._system_machine = SystemMachine(
            msg_handler=msg_handler,
            analysis=analysis,
            tunnel_device=hardware_model,
            pellet_device=hardware_model,
            inference=inference,
            topcam_presence=topcam_presence,
        ) if system_machine is None else system_machine

        self._project: Optional[ProjectInfo] = None
        self._hardware_model = hardware_model
        #
        self._source_algo_paused = "na"
        #
        system_machine.pellet.events.state_changed += lambda old_val, new_val: self._on_property_changed(
            f"pellet.{StateMachine.Properties.STATE_PROPERTY}", new_val, old_val)

        analysis.emergency_alarm_monitor.property_changed += self._alarm_monitor_property_changed

    @BehaviorAlgorithm.relay_func(wait=False)
    def _alarm_monitor_property_changed(self, name, value, old_value):
        logger.debug("alarm-mon: %s : %s -> %s", name, old_value, value)
        if name == EmergencyAlarmMonitor.IS_ENGAGED:
            if value:
                self.emergency_stop(f"alarm-monitor: {self._analysis.emergency_alarm_monitor.engaged_reasons}")
            else:
                self.emergency_resume("alarm-monitor-resumed")

    @property
    def analysis(self) -> SensorAnalysis:
        return self._analysis

    @property
    def project(self) -> ProjectInfo:
        return self._project

    @project.setter
    def project(self, value: ProjectInfo) -> None:
        self._project = value
        # self._machine.project = value  # instead of having to do it in on_prepare_capture()

    @property
    def system_machine(self) -> SystemMachine:
        return self._system_machine

    @property
    def algorithm(self) -> BehaviorAlgorithm:
        return self._system_machine.algorithm

    def load_configuration(self, config: BehaviorConfiguration):
        self._system_machine.algorithm.load_configuration(config)
        analysis = self._analysis
        analysis.headbar_pressure_monitor.load_configuration(config.headbar_pressure)
        analysis.load_cell_monitor.load_configuration(config.load_cell)
        analysis.load_cell_tare_monitor.load_configuration(config.auto_tare)
        analysis.audio_thrashing_monitor.config = config.audio
        analysis.emergency_alarm_monitor.config = config.emergency_alarm
        analysis.global_animal_presence_monitor.config = config.global_animal_presence
        analysis.external_doors_monitor.config = config.external_doors
        analysis.auto_tunnel_sweep_monitor.config = config.auto_tunnel_sweep

    def save_configuration(self) -> BehaviorConfiguration:
        config = self._system_machine.algorithm.active_config
        # makes copy on purpose, to ensure caller isn't able to modify current active config directly on that:
        return copy.deepcopy(config)

        config = BehaviorConfiguration()
        # orig_fields = dataclasses.fields(config)
        assigned = {}
        class ConfigWrap(BehaviorConfiguration):
            def __setattr__(self, key, value):
                assigned[key] = value

        wrap = ConfigWrap()
        save_config = config
        config = wrap

        algo = self._system_machine.algorithm
        algo.update_configuration(config)

        analysis = self._analysis
        config.load_cell = analysis.load_cell_monitor.save_configuration()
        config.auto_tare = analysis.load_cell_tare_monitor.save_configuration()
        config.headbar_pressure = analysis.headbar_pressure_monitor.save_configuration()
        config.audio = analysis.audio_thrashing_monitor.config
        config.emergency_alarm = analysis.emergency_alarm_monitor.config
        config.topcam_presence_detection = None if algo.top_camera_presence_detection is None else algo.top_camera_presence_detection.to_config()
        config.global_animal_presence = analysis.global_animal_presence_monitor.config
        config.external_doors = analysis.external_doors_monitor.config
        config.auto_tunnel_sweep = analysis.auto_tunnel_sweep_monitor.config

        dataclasses.replace(save_config, **assigned)
        config = save_config
        orig_fields = {f.name for f in dataclasses.fields(config)}
        missed = orig_fields - set(assigned)
        if len(missed) > 0:
            logger.warning("Fields %s not assigned / missed during save_config", missed)

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
        if self._hardware_model.head_magnet_intensity is not None:
            self._system_machine.algorithm.baseline_intensity = self._hardware_model.head_magnet_intensity

    def emergency_stop(self, source: str):
        algo = self._system_machine.algorithm
        logger.info("emergency_stop called: %s - current=%s", source, algo.algo_paused)
        if algo.algo_paused:
            return
        algo.algo_paused = True
        self._source_algo_paused = source
        EventManager.default().post_event_content(ApiEventKind.emergencyStop, dict(reason=source))
        self.emergency_stopped(source)

    def emergency_resume(self, source: str):
        algo = self._system_machine.algorithm
        logger.info("emergency_resume called: %s - current=%s", source, algo.algo_paused)
        if not algo.algo_paused:
            return
        if self._source_algo_paused == "user-button" and source != "user-button":
            logger.notice("Refusing resume from emergency given was set by user ; resume source=%s", source)
            return
        algo.algo_paused = False
        # restart full analysis so that monitors/detectors counters/context are reset, as if app was just started:
        self._analysis.restart()
        EventManager.default().post_event_content(ApiEventKind.emergencyResume, dict(reason=source))
        self.emergency_resumed(source)
