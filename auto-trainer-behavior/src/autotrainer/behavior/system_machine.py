import logging
from enum import Enum

from opentelemetry import trace
from transitions import Machine

from autotrainer.core import TriggerManager, CAPTURE_TRIGGER_ID, ProjectInfo, EventManager
from autotrainer.device import HeadFixReader, PelletReader

from .behavior_algorithm import BehaviorAlgorithm
from .behavior_limits import BehaviorLimits
from .behavior_event_kind import BehaviorEventKind
from .inference.inference_machine import InferenceMachine
from .inference_protocol import InferenceProtocol
from .intersession import IntersessionMachine

logger = logging.getLogger(__name__)

tracer = trace.get_tracer("behavior")


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
                 inference: InferenceProtocol = None, project_info: ProjectInfo = None):

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
            self._head_fix_reader.tare_callback = self._head_fix_tare_requested

        if self._head_fix_command is not None:
            self._head_fix_command.property_changed += self.head_fix_command_property_changed

        self._inference = InferenceMachine(self.algorithm, pellet_reader, pellet_command, inference)

        self._intersession = IntersessionMachine(self.algorithm, self._project_info, inference)
        self._intersession.events.on_analysis_ended += self.intersession_ended

        self._algorithm.session_ending += self.session_ended

        self._session_trace = None

    @property
    def algorithm(self):
        return self._algorithm

    @property
    def inference(self) -> InferenceMachine:
        return self._inference

    @property
    def intersession(self) -> IntersessionMachine:
        return self._intersession

    @property
    def project(self) -> ProjectInfo:
        return self._project_info

    @project.setter
    def project(self, value: ProjectInfo):
        self._project_info = value
        EventManager.instance().project = self._project_info
        self._algorithm.project = self._project_info
        self._intersession.project = self._project_info

    def before_enter_tunnel(self):
        EventManager.instance().post_event(BehaviorEventKind.tunnelEnter)

        if self._project_info is not None:
            self._project_info.calculate_next_session_index()

        self._session_trace = tracer.start_span("session")
        self.algorithm.start_session()

        TriggerManager.instance().trigger(self, CAPTURE_TRIGGER_ID, True)

        if self._head_fix_command is not None:
            self._head_fix_command.update_position(self.algorithm.baseline_intensity)

    def after_exit_tunnel(self):
        EventManager.instance().post_event(BehaviorEventKind.tunnelExit)
        self.algorithm.end_session()
        self._session_trace.end()

    def after_enter_intersession(self):
        self._intersession.perform_segmentation()

    def session_ended(self):
        TriggerManager.instance().trigger(self, CAPTURE_TRIGGER_ID, False)

        if self._head_fix_command is not None:
            self._head_fix_command.update_position(0)

        EventManager.instance().flush()

        if self.algorithm.can_perform_intersession_analysis():
            self.enter_intersession()

    def intersession_ended(self):
        if self.state == SystemState.intersession:
            self.exit_intersession()

    def head_fix_property_changed(self, name: str, value, _):
        if self.state == SystemState.intersession:
            EventManager.instance().post_event(BehaviorEventKind.headfixLoadCellChangedInIntersession, context=value)
            return
        else:
            EventManager.instance().post_event(BehaviorEventKind.headfixLoadCellChanged, context=value)

        if name == "is_load_cell_engaged":
            if value:
                if self.state == SystemState.cage:
                    self.enter_tunnel()
                else:
                    EventManager.instance().post_event(BehaviorEventKind.headfixLoadCellChangedWrongState,
                                                       context=self.state)
            else:
                if self.state == SystemState.tunnel:
                    self.exit_tunnel()
                else:
                    EventManager.instance().post_event(BehaviorEventKind.headfixLoadCellChangedWrongState,
                                                       context=self.state)

    def head_fix_command_property_changed(self, name: str, value, _):
        if name == "baseline_intensity":
            self.algorithm.baseline_intensity = value

    def _head_fix_tare_requested(self):
        if self.state != SystemState.tunnel:
            self._head_fix_command.tare()
            EventManager.instance().post_event(BehaviorEventKind.headfixAutoTare)

    # region State Machine Requirements
    # Methods required for model_override=True to work.
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
    # endregion
