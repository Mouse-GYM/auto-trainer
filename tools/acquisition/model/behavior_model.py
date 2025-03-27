from typing import Optional

from autotrainer.behavior import SystemMachine, BehaviorLimits, InferenceProtocol
from autotrainer.core import ObservableObject, ProjectInfo

from tools.acquisition.model.head_fix_model import HeadFixModel
from tools.acquisition.model.pellet_delivery_model import PelletDeliveryModel


class BehaviorModel(ObservableObject):
    def __init__(self, head_fix: HeadFixModel, pellet: PelletDeliveryModel, inference: InferenceProtocol):
        super().__init__()

        self._machine = SystemMachine(None, head_fix, pellet.pellet_reader, pellet, inference)

        self._project: Optional[ProjectInfo] = None

        self._is_intersession_enabled = False

    @property
    def project(self) -> ProjectInfo:
        return self._project

    @project.setter
    def project(self, value: ProjectInfo) -> None:
        self._project = value

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

    def load_configuration(self, configuration: dict):
        self._machine.algorithm.limits = BehaviorLimits.from_dictionary(configuration)

        if "isDeliverPelletEnabled" in configuration:
            self._machine.algorithm.pellet_delivery_enabled = configuration["isDeliverPelletEnabled"]
        if "isCoverPelletEnabled" in configuration:
            self._machine.algorithm.pellet_cover_enabled = configuration["isCoverPelletEnabled"]
        if "isIntersessionAnalysisEnabled" in configuration:
            self.is_intersession_enabled = configuration["isIntersessionAnalysisEnabled"]
        if "defaultBaselineIntensity" in configuration:
            self._machine.algorithm.baseline_intensity = configuration["defaultBaselineIntensity"]
        if "autoClampIntensity" in configuration:
            self._machine.algorithm.auto_clamp_intensity = configuration["autoClampIntensity"]

    def save_configuration(self) -> dict:
        limits = self._machine.algorithm.limits.to_dictionary()
        limits.update({"isDeliverPelletEnabled": self._machine.algorithm.pellet_delivery_enabled,
                       "isCoverPelletEnabled": self._machine.algorithm.pellet_cover_enabled,
                       "isIntersessionAnalysisEnabled": self._is_intersession_enabled,
                       "autoClampIntensity": self._machine.algorithm.auto_clamp_intensity})
        return limits

    def on_prepare_capture(self):
        self._machine.project = self._project

    def trigger_tunnel(self, value: bool):
        """
        Provides the ability to manually trigger tunnel enter/exit state changes independent of load cell events.
        Future load cell events will still have the expected behavior.
        :param value: True to enter tunnel, False to exit.
        :return:
        """
        if value:
            self._machine.enter_tunnel()
        else:
            self._machine.exit_tunnel()
