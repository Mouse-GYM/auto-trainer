from statemachine import StateMachine, State

from autotrainer.core import TriggerManager, CAPTURE_TRIGGER_ID
from tools.acquisition.behavior.behavior_model_properties import BehaviorModelProperties, BehaviorModelLimits
from tools.acquisition.behavior.cage_model import CageModel
from tools.acquisition.model.head_fix_model import HeadFixModel


class BehaviorModel2(StateMachine):
    # region States
    in_cage = State(initial=True)
    in_tunnel_idle = State()
    in_tunnel_pellet = State()
    in_tunnel_head_fixation = State()
    # endregion

    # region Transitions
    entered_tunnel = (
            in_cage.to(in_tunnel_idle, cond="analysis_is_busy") |
            in_cage.to(in_tunnel_head_fixation, cond="is_max_baseline_intensity") |
            in_cage.to(in_tunnel_pellet)
    )

    exited_tunnel = (
            in_tunnel_idle.to(in_cage) |
            in_tunnel_head_fixation.to(in_cage) |
            in_tunnel_pellet.to(in_cage)
    )

    # endregion

    def __init__(self, head_fix_model: HeadFixModel):
        super(BehaviorModel2, self).__init__(allow_event_without_transition=True)

        self._properties = BehaviorModelProperties(BehaviorModelLimits())

        self.cage_model = CageModel()

        self._head_fix_model = head_fix_model
        self._head_fix_model.property_changed += self.head_fix_property_changed

    # region Actions
    def after_entered_tunnel(self):
        self.cage_model.entered_tunnel()

        if self.cage_model.current_state.id != self.cage_model.analyzing.id:
            TriggerManager.instance().trigger(self, CAPTURE_TRIGGER_ID, True)

    def after_exited_tunnel(self):
        TriggerManager.instance().trigger(self, CAPTURE_TRIGGER_ID, False)

        self.cage_model.exited_tunnel()

    # endregion

    @property
    def properties(self):
        return self._properties

    def analysis_is_busy(self):
        return self.cage_model.current_state.id == self.cage_model.analyzing.id

    def is_max_baseline_intensity(self):
        return self.properties.baseline_intensity >= self.properties.limits.max_baseline_intensity

    def head_fix_property_changed(self, name: str, value, _):
        if name == "is_load_cell_engaged":
            if value:
                self.entered_tunnel()
            else:
                self.exited_tunnel()
