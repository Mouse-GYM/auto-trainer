from statemachine import StateMachine, State

from autotrainer.core import TriggerManager, CAPTURE_TRIGGER_ID
from tools.acquisition.behavior.behavior_model_properties import BehaviorModelProperties, BehaviorModelLimits
from tools.acquisition.model.head_fix_model import HeadFixModel


class BehaviorModel(StateMachine):
    in_cage = State(initial=True)
    in_tunnel = State()

    entered_tunnel = in_cage.to(in_tunnel)
    exited_tunnel = in_tunnel.to(in_cage)

    def __init__(self, head_fix_model: HeadFixModel):
        super(BehaviorModel, self).__init__(allow_event_without_transition=True)

        self._properties = BehaviorModelProperties(BehaviorModelLimits())

        self.head_fix_model = head_fix_model

        self.head_fix_model.property_changed += self.head_fix_property_changed

    def after_entered_tunnel(self):
        TriggerManager.instance().trigger(self, CAPTURE_TRIGGER_ID, True)

    def after_exited_tunnel(self):
        TriggerManager.instance().trigger(self, CAPTURE_TRIGGER_ID, False)

    @property
    def properties(self):
        return self._properties

    def head_fix_property_changed(self, name: str, value, _):
        if name == "is_load_cell_engaged":
            if value:
                self.entered_tunnel()
            else:
                self.exited_tunnel()
