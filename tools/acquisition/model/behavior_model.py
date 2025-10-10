import multiprocessing
from typing import Optional, Callable

from autotrainer.behavior import SystemMachine, InferenceProtocol, BehaviorAlgorithm
from autotrainer.behavior.behavior_algorithm import BehaviorAlgoProps
from autotrainer.behavior.state_machine import StateMachine
from autotrainer.core import (ObservableObject, ProjectInfo, SensorAnalysis, BehaviorConfiguration,
                              SystemMessageHandler, EventManager, ApiEventKind)
from tools.acquisition.model.hardware_model import HardwareModel

from tools.acquisition.model.project_dependent_protocol import ProjectDependentProtol


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
    ):
        super().__init__(("emergency_stopped", "emergency_resumed"))

        self._analysis = analysis

        self._system_machine = SystemMachine(
            algorithm=None,
            project_info=None,
            msg_handler=msg_handler,
            analysis=analysis,
            tunnel_device=hardware_model,
            pellet_device=hardware_model,
            inference=inference,
        )

        self._project: Optional[ProjectInfo] = None
        self._is_intersession_enabled = self._system_machine.algorithm.intersession_enabled
        self._hardware_model = hardware_model
        #
        self._system_machine.algorithm.property_changed += self._on_algorithm_property_changed
        self._system_machine.pellet.events.state_changed += lambda old_val, new_val: self._on_property_changed(
            f"pellet.{StateMachine.Properties.STATE_PROPERTY}", new_val, old_val)

        @BehaviorAlgorithm.relay_func
        def alarm_monitor_property_changed(name, value, _):
            if name == "is_engaged":
                meth = self.emergency_stop if value else self.emergency_resume
                meth("alarm-monitor")  # noqa
        analysis.emergency_alarm_monitor.property_changed += alarm_monitor_property_changed

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
    def algorithm(self):
        return self._system_machine.algorithm

    @property
    def is_intersession_enabled(self) -> bool:
        return self._is_intersession_enabled

    @is_intersession_enabled.setter
    def is_intersession_enabled(self, value: bool) -> None:
        self._is_intersession_enabled = self._on_property_changed("is_intersession_enabled", value,
                                                                  self._is_intersession_enabled)
        self._system_machine.algorithm.intersession_enabled = self._is_intersession_enabled

    def load_configuration(self, configuration: BehaviorConfiguration):
        self.is_intersession_enabled = configuration.pellet_delivery.is_intersession_analysis_enabled
        self._system_machine.algorithm.load_configuration(configuration)

    def save_configuration(self) -> BehaviorConfiguration:
        configuration = BehaviorConfiguration()
        algo = self._system_machine.algorithm
        pellet_deliver_cfg = configuration.pellet_delivery
        pellet_deliver_cfg.is_intersession_analysis_enabled = self._is_intersession_enabled
        pellet_deliver_cfg.is_intersession_pellet_shift_enabled = algo.intersession_pellet_shift_enabled
        algo.update_configuration(configuration)

        analysis = self._analysis
        configuration.load_cell = analysis.load_cell_monitor.save_configuration()
        configuration.auto_tare = analysis.load_cell_tare_monitor.save_configuration()
        configuration.headbar_pressure = analysis.headbar_pressure_monitor.save_configuration()
        configuration.audio = analysis.audio_thrashing_monitor.config
        configuration.emergency_alarm = analysis.emergency_alarm_monitor.config

        return configuration

    def on_prepare_capture(self):
        self._system_machine.project = self._project

    def use_current_head_magnet_position_as_baseline(self):
        if self._hardware_model.head_magnet_intensity is not None:
            self.algorithm.baseline_intensity = self._hardware_model.head_magnet_intensity

    def emergency_stop(self, source: str):
        self.algorithm.algo_paused = True
        EventManager.default().post_event_content(ApiEventKind.emergencyStop, source)
        self.emergency_stopped(source)

    def emergency_resume(self, source: str):
        self.algorithm.algo_paused = False
        EventManager.default().post_event_content(ApiEventKind.emergencyResume, source)
        self.emergency_resumed(source)

    def _on_algorithm_property_changed(self, property_name: str, value, _):
        if property_name == BehaviorAlgoProps.INTERSESSION_ENABLED:
            self._is_intersession_enabled = value

    def trigger_tunnel(self, value: bool):
        # currently unused
        """
        Provides the ability to manually trigger tunnel enter/exit state changes independent of load cell events.
        Future load cell events will still have the expected behavior.  This is primarily supported for testing and
        diagnostics.

        :param value: True to enter tunnel, False to exit.

        :return:
        """
        if value:
            self._system_machine.enter_tunnel(reason="simulate_enter_tunnel")
        else:
            self._system_machine.exit_tunnel(reason="simulate_exit_tunnel")
