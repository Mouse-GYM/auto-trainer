import logging

from autotrainer.core import TriggerManager, CAPTURE_TRIGGER_ID
from autotrainer.device import HeadFixReader, PelletReader
from autotrainer.inference import PoseAlgorithm

from .behavior_model_base import BehaviorModelBase
from .behavior_properties import BehaviorProperties
from .behavior_limits import BehaviorLimits
from .inference.inference_behavior_model import InferenceBehaviorModel

logger = logging.getLogger(__name__)


class BehaviorModel(BehaviorModelBase):
    def __init__(self, head_fix: HeadFixReader, pellet_device: PelletReader, pellet_command, pose: PoseAlgorithm):
        super().__init__()

        self._properties = BehaviorProperties(BehaviorLimits())

        self.head_fix = head_fix

        if self.head_fix is not None:
            self.head_fix.property_changed += self.head_fix_property_changed

        self.pellet_device = pellet_device

        self.pellet_command = pellet_command

        self.pose = pose

        self._inference = InferenceBehaviorModel(self._properties, pellet_device, pellet_command, pose)

    def before_enter_tunnel(self):
        TriggerManager.instance().trigger(self, CAPTURE_TRIGGER_ID, True)
        self._properties.start_session()

    def before_exit_tunnel(self):
        TriggerManager.instance().trigger(self, CAPTURE_TRIGGER_ID, False)

    def after_exit_tunnel(self):
        pass

    @property
    def properties(self):
        return self._properties

    def head_fix_property_changed(self, name: str, value, _):
        if name == "is_load_cell_engaged":
            if value:
                self.enter_tunnel()
            else:
                self.exit_tunnel()

