from autotrainer.behavior import SystemMachine, BehaviorLimits
from autotrainer.core import ObservableObject, ProjectInfo
from autotrainer.device import HeadFixReader, PelletReader
from autotrainer.inference import PoseAlgorithm


class BehaviorModel(ObservableObject):
    def __init__(self, head_fix_reader: HeadFixReader, head_fix, pellet_device: PelletReader,
                 pellet_command, pose: PoseAlgorithm):
        super().__init__()

        self._machine = SystemMachine(None, head_fix_reader, head_fix, pellet_device, pellet_command, pose)

    def load_configuration(self, values: dict):
        self._machine.algorithm.limits = BehaviorLimits.from_dictionary(values)

    def on_prepare_capture(self, project_info: ProjectInfo):
        self._machine.project = project_info

    def trigger_tunnel(self, value: bool):
        if value:
            self._machine.enter_tunnel()
        else:
            self._machine.exit_tunnel()
