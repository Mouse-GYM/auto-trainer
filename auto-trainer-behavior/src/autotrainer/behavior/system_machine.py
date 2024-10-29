import logging
from enum import Enum

from transitions import Machine

from autotrainer.core import TriggerManager, CAPTURE_TRIGGER_ID, ProjectInfo
from autotrainer.device import HeadFixReader, PelletReader
from autotrainer.inference import PoseAlgorithm

from .behavior_algorithm import BehaviorAlgorithm
from .behavior_limits import BehaviorLimits
from .inference.inference_machine import InferenceMachine
from .intersession import IntersessionMachine

logger = logging.getLogger(__name__)


class SystemState(str, Enum):
    cage = "cage",
    tunnel = "tunnel",
    intersession = "intersession"


class SystemMachine:
    states = [e for e in SystemState]

    transitions = [
        {"trigger": "enter_tunnel", "source": SystemState.cage, "dest": SystemState.tunnel,
         "before": "before_enter_tunnel"},
        {"trigger": "exit_tunnel", "source": SystemState.tunnel, "dest": SystemState.cage,
         "after": "after_exit_tunnel"},
        {"trigger": "enter_intersession", "source": SystemState.cage, "dest": SystemState.intersession,
         "after": "after_enter_intersession"},
        {"trigger": "exit_intersession", "source": SystemState.intersession, "dest": SystemState.cage}
    ]

    def __init__(self, algorithm: BehaviorAlgorithm = None, head_fix_reader: HeadFixReader = None,
                 head_fix_command=None, pellet_reader: PelletReader = None, pellet_command=None,
                 pose: PoseAlgorithm = None, pose_command=None, project_info: ProjectInfo = None):

        self.state = SystemState.cage

        self.machine = Machine(model=self, states=SystemMachine.states, transitions=SystemMachine.transitions,
                               auto_transitions=False, initial=SystemState.cage, model_override=True)

        self._project_info = project_info

        self._algorithm = algorithm if algorithm is not None else BehaviorAlgorithm(BehaviorLimits())
        self._algorithm.project = self._project_info

        self._head_fix_command = head_fix_command

        self._head_fix_reader = head_fix_reader

        if self._head_fix_reader is not None:
            self._head_fix_reader.property_changed += self.head_fix_property_changed

        self._inference = InferenceMachine(self.algorithm, pellet_reader, pellet_command, pose)

        self._intersession = IntersessionMachine(self.algorithm, pose, pose_command)

        self._algorithm.session_ending += self.session_ended

    @property
    def algorithm(self):
        return self._algorithm

    @property
    def inference(self) -> InferenceMachine:
        return self._inference

    @property
    def project(self) -> ProjectInfo:
        return self._project_info

    @project.setter
    def project(self, value: ProjectInfo):
        self._project_info = value
        self._algorithm.project = self._project_info

    def before_enter_tunnel(self):
        if self._project_info is not None:
            self._project_info.calculate_next_session_index()

        self.algorithm.start_session()

        TriggerManager.instance().trigger(self, CAPTURE_TRIGGER_ID, True)

        self._inference.before_enter_tunnel()

        if self._head_fix_command is not None:
            self._head_fix_command.update_position(self.algorithm.baseline_intensity)

    def after_exit_tunnel(self):
        self._inference.after_exit_tunnel()

        self.algorithm.end_session()

    def after_enter_intersession(self):
        self._intersession.perform_segmentation()

    def session_ended(self):
        TriggerManager.instance().trigger(self, CAPTURE_TRIGGER_ID, False)

        if self._head_fix_command is not None:
            self._head_fix_command.update_position(0)

        # if self.algorithm.session_mouse_seen:
        #    self.enter_intersession()

    def head_fix_property_changed(self, name: str, value, _):
        if self.state == SystemState.intersession:
            return

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

    def enter_intersession(self):
        pass

    def may_enter_intersession(self):
        pass

    def exit_intersession(self):
        pass

    def may_exit_intersession(self):
        pass

    def is_cage(self):
        pass

    def is_tunnel(self):
        pass

    def is_intersession(self):
        pass
