import logging
from enum import Enum

from transitions.extensions import HierarchicalMachine

from autotrainer.core import TriggerManager, CAPTURE_TRIGGER_ID
from autotrainer.device import HeadFixReader, PelletReader
from autotrainer.inference import PoseAlgorithm

from .behavior_algorithm import BehaviorAlgorithm
from .behavior_limits import BehaviorLimits
from .inference.inference_behavior_machine import InferenceBehaviorMachine

logger = logging.getLogger(__name__)


class SystemState(str, Enum):
    cage = "cage",
    tunnel = "tunnel"


class SystemBehaviorMachine:
    states = [e for e in SystemState]

    transitions = [
        {"trigger": "enter_tunnel", "source": "*", "dest": SystemState.tunnel, "before": "before_enter_tunnel"},
        {"trigger": "exit_tunnel", "source": "*", "dest": SystemState.cage, "after": "after_exit_tunnel"},
    ]

    def __init__(self, algorithm: BehaviorAlgorithm = None, head_fix_reader: HeadFixReader = None,
                 head_fix_command=None, pellet_reader: PelletReader = None, pellet_command=None,
                 pose: PoseAlgorithm = None):

        self.state = SystemState.cage

        self.machine = HierarchicalMachine(model=self, states=SystemBehaviorMachine.states,
                                           transitions=SystemBehaviorMachine.transitions, auto_transitions=False,
                                           initial=SystemState.cage, model_override=True)

        self._algorithm = algorithm if algorithm is not None else BehaviorAlgorithm(BehaviorLimits())

        self._head_fix_command = head_fix_command

        self._head_fix_reader = head_fix_reader

        if self._head_fix_reader is not None:
            self._head_fix_reader.property_changed += self.head_fix_property_changed

        self._inference = InferenceBehaviorMachine(self.algorithm, pellet_reader, pellet_command, pose)

        self._algorithm.session_ending += self.end_session

    @property
    def algorithm(self):
        return self._algorithm

    @property
    def inference(self) -> InferenceBehaviorMachine:
        return self._inference

    def before_enter_tunnel(self):
        self.algorithm.start_session()

        TriggerManager.instance().trigger(self, CAPTURE_TRIGGER_ID, True)

        self._inference.before_enter_tunnel()

        if self._head_fix_command is not None:
            self._head_fix_command.update_position(self.algorithm.baseline_intensity)

    def after_exit_tunnel(self):
        self._inference.after_exit_tunnel()

        self.algorithm.end_session()

    def end_session(self):
        TriggerManager.instance().trigger(self, CAPTURE_TRIGGER_ID, False)

        if self._head_fix_command is not None:
            self._head_fix_command.update_position(0)

    def head_fix_property_changed(self, name: str, value, _):
        if name == "is_load_cell_engaged":
            if value:
                self.enter_tunnel()
            else:
                self.exit_tunnel()

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
