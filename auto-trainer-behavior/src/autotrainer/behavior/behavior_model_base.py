from enum import Enum

from transitions.extensions import HierarchicalMachine


class SystemState(str, Enum):
    cage = "cage",
    tunnel = "tunnel"


class BehaviorModelBase:
    states = [e for e in SystemState]

    transitions = [
        {"trigger": "enter_tunnel", "source": "*", "dest": SystemState.tunnel,
         "before": "before_enter_tunnel"},
        {"trigger": "exit_tunnel", "source": "*", "dest": SystemState.cage,
         "before": "before_exit_tunnel", "after": "after_exit_tunnel"},
    ]

    def __init__(self):
        self.state = SystemState.cage

        self.machine = HierarchicalMachine(model=self, states=BehaviorModelBase.states,
                                           transitions=BehaviorModelBase.transitions, auto_transitions=False,
                                           initial=SystemState.cage, model_override=True)

    def trigger(self):
        pass

    def may_trigger(self):
        pass

    def enter_tunnel(self):
        pass

    def may_enter_tunnel(self):
        pass

    def exit_tunnel(self):
        pass

    def may_exit_tunnel(self):
        pass

    def is_cage(self):
        pass

    def is_tunnel(self):
        pass
