import logging
from enum import Enum

from transitions.extensions import HierarchicalMachine

from autotrainer.core import TriggerManager, CAPTURE_TRIGGER_ID
from tools.acquisition.behavior.behavior_model_properties import BehaviorModelProperties, BehaviorModelLimits
from tools.acquisition.model.head_fix_model import HeadFixModel

logger = logging.getLogger(__name__)


class SystemStates(str, Enum):
    InCage = "in-cage"
    PelletDelivery = "pellet-delivery"


class PelletDeliveryStates(str, Enum):
    Idle = "idle"
    Missing = "missing"
    Loading = "loading"
    Sending = "sending"
    Releasing = "releasing"

    def full_name(self):
        return f"{SystemStates.PelletDelivery}_{self}"


class BehaviorModelTransitions(object):
    pellet_delivery_states = {"name": SystemStates.PelletDelivery, "initial": PelletDeliveryStates.Idle,
                              "children": [PelletDeliveryStates.Idle, PelletDeliveryStates.Missing,
                                           PelletDeliveryStates.Loading, PelletDeliveryStates.Sending,
                                           PelletDeliveryStates.Releasing]}

    states = [SystemStates.InCage, pellet_delivery_states]

    transitions = [
        {"trigger": "enter_tunnel", "source": "*", "dest": SystemStates.PelletDelivery,
         "before": "before_entered_tunnel"},
        {"trigger": "exit_tunnel", "source": "*", "dest": SystemStates.InCage,
         "after": "after_exited_tunnel"},
        ["pellet_seen", "*", SystemStates.PelletDelivery]
    ]

    def __init__(self, head_fix_model: HeadFixModel):
        super().__init__()

        self.machine = HierarchicalMachine(model=self, states=BehaviorModelTransitions.states,
                                           transitions=BehaviorModelTransitions.transitions,
                                           initial=SystemStates.InCage)

        self._properties = BehaviorModelProperties(BehaviorModelLimits())

        if head_fix_model is not None:
            self.head_fix_model = head_fix_model

            self.head_fix_model.property_changed += self.head_fix_property_changed

    def before_entered_tunnel(self):
        TriggerManager.instance().trigger(self, CAPTURE_TRIGGER_ID, True)

    def after_exited_tunnel(self):
        TriggerManager.instance().trigger(self, CAPTURE_TRIGGER_ID, False)

    @property
    def properties(self):
        return self._properties

    def head_fix_property_changed(self, name: str, value, _):
        if name == "is_load_cell_engaged":
            if value:
                self.enter_tunnel()
            else:
                self.exit_tunnel()
