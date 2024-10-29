from autotrainer.behavior import SystemMachine, BehaviorLimits
from autotrainer.core import ObservableObject, ProjectInfo
from autotrainer.device import HeadFixReader, PelletReader
from autotrainer.inference import PoseAlgorithm


class BehaviorModel(ObservableObject):
    def __init__(self, head_fix_reader: HeadFixReader, head_fix, pellet_device: PelletReader,
                 pellet_command, pose: PoseAlgorithm):
        super().__init__()

        self._machine = SystemMachine(None, head_fix_reader, head_fix, pellet_device, pellet_command, pose)

    @property
    def algorithm(self):
        return self._machine.algorithm

    def load_configuration(self, values: dict):
        self._machine.algorithm.limits = BehaviorLimits.from_dictionary(values)

        if "isDeliverPelletEnabled" in values:
            self._machine.algorithm.pellet_delivery_enabled = values["isDeliverPelletEnabled"]
        if "isCoverPelletEnabled" in values:
            self._machine.algorithm.pellet_cover_enabled = values["isCoverPelletEnabled"]

    def write_configuration(self):
        limits = self._machine.algorithm.limits.to_dictionary()
        limits.update({"isDeliverPelletEnabled": self._machine.algorithm.pellet_delivery_enabled, "isCoverPelletEnabled": self._machine.algorithm.pellet_cover_enabled})
        return limits

    def on_prepare_capture(self, project_info: ProjectInfo):
        self._machine.project = project_info

    def trigger_tunnel(self, value: bool):
        if value:
            self._machine.enter_tunnel()
        else:
            self._machine.exit_tunnel()
