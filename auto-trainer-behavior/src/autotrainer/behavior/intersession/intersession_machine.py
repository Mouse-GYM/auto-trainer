import logging
import secrets
from enum import Enum

from events import Events
from transitions import Machine

from autotrainer.core import ProjectInfo, EventManager
from ..behavior_event_kind import BehaviorEventKind

from ..inference_protocol import InferenceProtocol, SegmentationConfiguration, DetectionConfiguration
from ..behavior_algorithm import BehaviorAlgorithm

logger = logging.getLogger(__name__)


class IntersessionState(str, Enum):
    idle = "idle",
    segmentation = "segmentation",
    detection = "detection"


class IntersessionMachine:
    states = [e for e in IntersessionState]

    transitions = [
        {"trigger": "perform_segmentation", "source": IntersessionState.idle, "dest": IntersessionState.segmentation,
         "after": "after_enter_segmentation", "conditions": "can_perform_segmentation"},
        {"trigger": "perform_detection", "source": IntersessionState.segmentation, "dest": IntersessionState.detection,
         "after": "after_enter_detection", "conditions": "can_perform_detection"},
        {"trigger": "end_analysis", "source": [IntersessionState.segmentation, IntersessionState.detection],
         "dest": IntersessionState.idle, "after": "after_end_analysis"},
    ]

    def __init__(self, algorithm: BehaviorAlgorithm, project_info: ProjectInfo = None,
                 inference: InferenceProtocol = None):
        self.state = IntersessionState.idle

        self._machine = Machine(model=self, states=IntersessionMachine.states, ignore_invalid_triggers=True,
                                transitions=IntersessionMachine.transitions, auto_transitions=False,
                                initial=IntersessionState.idle, model_override=True)

        self._project_info = project_info

        self._algorithm = algorithm

        self._inference = inference

        self._segmentation_configuration = None

        self._detection_configuration = None

        self.events = Events(events=("on_analysis_ended",))

    @property
    def project(self):
        return self._project_info

    @project.setter
    def project(self, project):
        self._project_info = project

    def after_enter_segmentation(self):
        self._segmentation_configuration = SegmentationConfiguration(nonce=secrets.token_hex(),
                                                                     session_index=self._project_info.session,
                                                                     complete=self._segmentation_complete)
        EventManager.instance().post_event(BehaviorEventKind.intersessionSegmentationBegin,
                                           context=self._segmentation_configuration.nonce)
        self._inference.perform_segmentation(self._segmentation_configuration)

    def after_enter_detection(self):
        self._detection_configuration = DetectionConfiguration(nonce=secrets.token_hex(),
                                                               complete=self._detection_complete)
        EventManager.instance().post_event(BehaviorEventKind.intersessionDetectionBegin,
                                           context=self._segmentation_configuration.nonce)
        self._inference.perform_detection(self._detection_configuration)

    def after_end_analysis(self):
        self.events.on_analysis_ended()

    def can_perform_segmentation(self):
        EventManager.instance().post_event(BehaviorEventKind.intersessionSegmentationCan,
                                           context=f"{self._project_info is not None}:{self._inference is not None}:{self._segmentation_configuration is None}")
        return self._project_info is not None and self._inference is not None and self._segmentation_configuration is None

    def can_perform_detection(self):
        EventManager.instance().post_event(BehaviorEventKind.intersessionDetectionCan,
                                           context=f"{self._project_info is not None}:{self._inference is not None}:{self._detection_configuration is None}")
        return self._project_info is not None and self._inference is not None and self._detection_configuration is None

    def _segmentation_complete(self, nonce: str, success: bool):
        if self._segmentation_configuration.nonce != nonce:
            logger.error("mismatched segmentation nonce")
            EventManager.instance().post_event(BehaviorEventKind.intersessionSegmentationNonceMismatch,
                                               context=f"{self._segmentation_configuration.nonce}:{nonce}")
            self.end_analysis()
        else:
            if success:
                EventManager.instance().post_event(BehaviorEventKind.intersessionSegmentationEnd)
                self.perform_detection()
            else:
                logger.error("perform segmentation failed")
                EventManager.instance().post_event(BehaviorEventKind.intersessionSegmentationError)
                self.end_analysis()

        self._segmentation_configuration = None

    def _detection_complete(self, nonce: str, success: bool):
        if self._detection_configuration.nonce != nonce:
            logger.error("mismatched detection nonce")
            EventManager.instance().post_event(BehaviorEventKind.intersessionDetectionNonceMismatch,
                                               context=f"{self._detection_configuration.nonce}:{nonce}")
            self.end_analysis()
        else:
            if not success:
                logger.error("perform detection failed")
                EventManager.instance().post_event(BehaviorEventKind.intersessionDetectionError)
            else:
                EventManager.instance().post_event(BehaviorEventKind.intersessionDetectionEnd)

            self.end_analysis()

        self._detection_configuration = None

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
