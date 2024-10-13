import logging

from autotrainer.core import TriggerManager, CAPTURE_TRIGGER_ID
from autotrainer.device import HeadFixReader, PelletReader
from autotrainer.inference import PoseAlgorithm

from .behavior_algorithm import BehaviorAlgorithm
from .system_behavior_machine_base import SystemBehaviorMachineBase
from .inference.inference_behavior_machine import InferenceBehaviorMachine

logger = logging.getLogger(__name__)


class SystemBehaviorMachine(SystemBehaviorMachineBase):
    def __init__(self, head_fix: HeadFixReader, pellet_device: PelletReader, pellet_command, pose: PoseAlgorithm,
                 properties: BehaviorAlgorithm = None):
        super().__init__(properties)

        self.head_fix = head_fix

        if self.head_fix is not None:
            self.head_fix.property_changed += self.head_fix_property_changed

        self._inference = InferenceBehaviorMachine(self.algorithm, pellet_device, pellet_command, pose)

    @property
    def inference(self):
        return self._inference

    def before_enter_tunnel(self):
        TriggerManager.instance().trigger(self, CAPTURE_TRIGGER_ID, True)
        self.algorithm.start_session()

    def before_exit_tunnel(self):
        TriggerManager.instance().trigger(self, CAPTURE_TRIGGER_ID, False)

    def after_exit_tunnel(self):
        pass

    def head_fix_property_changed(self, name: str, value, _):
        if name == "is_load_cell_engaged":
            if value:
                self.enter_tunnel()
            else:
                self.exit_tunnel()
