from enum import Enum

from transitions.extensions import HierarchicalMachine

from .behavior_algorithm import BehaviorAlgorithm
from .behavior_limits import BehaviorLimits


class SystemState(str, Enum):
    cage = "cage",
    tunnel = "tunnel"


class SystemBehaviorMachineBase:
    states = [e for e in SystemState]

    transitions = [
        {"trigger": "enter_tunnel", "source": "*", "dest": SystemState.tunnel,
         "before": "before_enter_tunnel"},
        {"trigger": "exit_tunnel", "source": "*", "dest": SystemState.cage,
         "before": "before_exit_tunnel", "after": "after_exit_tunnel"},
    ]

    def __init__(self, properties: BehaviorAlgorithm = None):
        self.state = SystemState.cage

        self.machine = HierarchicalMachine(model=self, states=SystemBehaviorMachineBase.states,
                                           transitions=SystemBehaviorMachineBase.transitions, auto_transitions=False,
                                           initial=SystemState.cage, model_override=True)

        self._algorithm = properties if properties is not None else BehaviorAlgorithm(BehaviorLimits())

    @property
    def algorithm(self):
        return self._algorithm

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
