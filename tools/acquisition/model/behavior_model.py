from autotrainer.behavior import SystemBehaviorMachine, BehaviorLimits
from autotrainer.core import ObservableObject
from autotrainer.device import HeadFixReader, PelletReader
from autotrainer.inference import PoseAlgorithm


class BehaviorModel(ObservableObject):
    def __init__(self, head_fix_reader: HeadFixReader, head_fix, pellet_device: PelletReader, pellet_command,
                 pose: PoseAlgorithm):
        super().__init__()

        self._machine = SystemBehaviorMachine(None, head_fix_reader, head_fix, pellet_device, pellet_command, pose)

    def load_configuration(self, values: dict):
        self._machine.algorithm.limits = BehaviorLimits.from_dictionary(values)
