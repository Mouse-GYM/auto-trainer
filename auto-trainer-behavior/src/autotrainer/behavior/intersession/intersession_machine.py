import logging
from enum import Enum

from transitions import Machine

from autotrainer.inference import PoseAlgorithm, PoseResponse

from ..behavior_algorithm import BehaviorAlgorithm

logger = logging.getLogger(__name__)


class IntersessionState(str, Enum):
    idle = "idle",
    segmentation = "segmentation",
    detection = "detection"


class IntersessionMachine:
    states = [e for e in IntersessionState]

    transitions = [
        {"trigger": "perform_segmentation", "source": IntersessionState.idle, "dest": IntersessionState.segmentation},
        {"trigger": "perform_detection", "source": IntersessionState.segmentation, "dest": IntersessionState.detection},
        {"trigger": "end_analysis", "source": IntersessionState.detection, "dest": IntersessionState.idle},
    ]

    def __init__(self, algorithm: BehaviorAlgorithm, pose: PoseAlgorithm = None):
        self.state = IntersessionState.idle

        self._machine = Machine(model=self, states=IntersessionMachine.states,
                                transitions=IntersessionMachine.transitions, auto_transitions=False,
                                initial=IntersessionState.idle, model_override=True)

        self._algorithm = algorithm

        self._pose = pose

        if self._pose is not None:
            self._pose.pose_changed += self.pose_changed

    def pose_changed(self, response: PoseResponse):
        pass

    # region State Machine Requirements
    # Methods required for model_override=True to work.
    def trigger(self):
        pass

    def may_trigger(self):
        pass

    def perform_segmentation(self):
        pass

    def may_perform_segmentation(self):
        pass

    def perform_detection(self):
        pass

    def may_perform_detection(self):
        pass

    def end_analysis(self):
        pass

    def may_end_analysis(self):
        pass

    def is_idle(self):
        pass

    def is_segmentation(self):
        pass

    def is_detection(self):
        pass

    # endregion
