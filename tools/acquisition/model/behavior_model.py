from typing import Optional

from autotrainer.behavior import SystemMachine, InferenceProtocol
from autotrainer.behavior.behavior_algorithm import BehaviorAlgoProps
from autotrainer.behavior.state_machine import StateMachine
from autotrainer.core import ObservableObject, ProjectInfo, MessageHandler, SensorAnalysis, BehaviorConfiguration
from autotrainer.video.detection import PresenceDetectionAttrs
from tools.acquisition.model.hardware_model import HardwareModel

from tools.acquisition.model.project_dependent_protocol import ProjectDependentProtol


class BehaviorModel(ObservableObject, ProjectDependentProtol):
    def __init__(
        self,
        msg_handler: MessageHandler,
        analysis: SensorAnalysis,
        hardware_model: HardwareModel,
        inference: InferenceProtocol,
    ):
        super().__init__()

        self._analysis = analysis

        self._machine = SystemMachine(
            algorithm=None,
            project_info=None,
            msg_handler=msg_handler,
            analysis=analysis,
            tunnel_device=hardware_model,
            pellet_device=hardware_model,
            inference=inference,
        )

        self._project: Optional[ProjectInfo] = None

        self._machine.algorithm.property_changed += self._on_algorithm_property_changed
        self._machine.pellet.events.state_changed += lambda old_val, new_val: self._on_property_changed(
            f"pellet.{StateMachine.Properties.STATE_PROPERTY}", new_val, old_val)

        self._is_intersession_enabled = self._machine.algorithm.intersession_enabled
        self._hardware_model = hardware_model

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
    def algorithm(self):
        return self._machine.algorithm

    @property
    def is_intersession_enabled(self) -> bool:
        return self._is_intersession_enabled

    @is_intersession_enabled.setter
    def is_intersession_enabled(self, value: bool) -> None:
        self._is_intersession_enabled = self._on_property_changed("is_intersession_enabled", value,
                                                                  self._is_intersession_enabled)
        self._machine.algorithm.intersession_enabled = self._is_intersession_enabled

    def load_configuration(self, configuration: BehaviorConfiguration):
        self.is_intersession_enabled = configuration.pellet_delivery.is_intersession_analysis_enabled
        self._machine.algorithm.load_configuration(configuration)

    def save_configuration(self) -> BehaviorConfiguration:
        configuration = BehaviorConfiguration()
        configuration.pellet_delivery.is_intersession_analysis_enabled = self._is_intersession_enabled
        configuration.pellet_delivery.is_intersession_pellet_shift_enabled = (
            self._machine.algorithm.intersession_pellet_shift_enabled)

        self._machine.algorithm.update_configuration(configuration)

        configuration.load_cell = self._analysis.load_cell_monitor.save_configuration()
        configuration.auto_tare = self._analysis.load_cell_tare_monitor.save_configuration()
        configuration.headbar_pressure = self._analysis.headbar_pressure_monitor.save_configuration()

        return configuration

    def on_prepare_capture(self):
        self._machine.project = self._project

    def use_current_head_magnet_position_as_baseline(self):
        if self._hardware_model.head_magnet_intensity is not None:
            self.algorithm.baseline_intensity = self._hardware_model.head_magnet_intensity

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
            self._machine.enter_tunnel(reason="simulate_enter_tunnel")
        else:
            self._machine.exit_tunnel(reason="simulate_exit_tunnel")
