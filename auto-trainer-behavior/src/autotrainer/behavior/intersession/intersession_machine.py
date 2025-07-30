import logging
import secrets
from enum import Enum

from transitions import Machine

from autotrainer.core import ProjectInfo, EventManager, ObservableObject
from ..behavior_event_kind import BehaviorEventKind

from ..inference_protocol import InferenceProtocol, SegmentationConfiguration, DetectionConfiguration
from ..behavior_algorithm import BehaviorAlgorithm
from ..state_machine import StateMachine
from autotrainer.core.logging import get_verbose_logger

logger = get_verbose_logger(__name__)


class IntersessionState(str, Enum):
    idle = "idle"
    segmentation = "segmentation"
    detection = "detection"


class IntersessionMachine(StateMachine):
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

        initial_state = IntersessionState.idle

        super().__init__(initial_state=initial_state, event_names=("on_analysis_started", "on_analysis_ended"))

        self._machine = Machine(model=[self], states=IntersessionMachine.states,
                                transitions=IntersessionMachine.transitions, auto_transitions=False,
                                initial=initial_state, model_override=True)

        self._project_info = project_info
        self._algorithm = algorithm
        self._inference = inference
        self._segmentation_configuration = None
        self._detection_configuration = None

    @property
    def project(self):
        return self._project_info

    @project.setter
    def project(self, project):
        self._project_info = project

    def after_enter_segmentation(self):
        self.events.on_analysis_started()
        segment_config = self._segmentation_configuration = SegmentationConfiguration(nonce=secrets.token_hex(),
                                                                     session_index=self._project_info.session.value,
                                                                     complete=self._segmentation_complete)
        EventManager.default().post_event_content(BehaviorEventKind.intersessionSegmentationBegin,
                                                  context=segment_config.nonce)
        self._inference.perform_segmentation(segment_config)

    def after_enter_detection(self):
        detect_config = self._detection_configuration = DetectionConfiguration(nonce=secrets.token_hex(),
                                                               complete=self._detection_complete)
        EventManager.default().post_event_content(BehaviorEventKind.intersessionDetectionBegin,
                                                  context=self._segmentation_configuration.nonce)
        self._inference.perform_detection(detect_config)

    def after_end_analysis(self):
        self.events.on_analysis_ended()

    def can_perform_segmentation(self):
        p = self._project_info is not None
        i = self._inference is not None
        s = self._segmentation_configuration is not None
        EventManager.default().post_event_content(
            BehaviorEventKind.intersessionSegmentationCan, context=f"{p}:{i}:{not s}")
        res = p and i and not s
        logger.debug("can_perform_segmentation=%s: prj=%s inference=%s segment=%s", res, p, i, s)
        return res

    def can_perform_detection(self):
        p = self._project_info is not None
        i = self._inference is not None
        d = self._detection_configuration is None
        EventManager.default().post_event_content(BehaviorEventKind.intersessionDetectionCan,
                                                  context=f"{p}:{i}:{d}")
        can_do_detection = p and i and d
        logger.debug("can_perform_detection=%s ; prj=%s inference=%s detection_config=%s",
                    can_do_detection, p, i, d)
        return can_do_detection

    def _segmentation_complete(self, nonce: str, success: bool):
        segment_config = self._segmentation_configuration
        if segment_config.nonce != nonce:
            logger.error("mismatched segmentation nonce: passed=%s cur_seg_config=%s success=%s",
                         nonce, segment_config, success)
            EventManager.default().post_event_content(BehaviorEventKind.intersessionSegmentationNonceMismatch,
                                                      context=f"{segment_config.nonce}:{nonce}")
            self.end_analysis()
        else:
            if success:
                EventManager.default().post_event_content(BehaviorEventKind.intersessionSegmentationEnd)
                self.perform_detection()
            else:
                logger.error("perform segmentation failed. config=%s", segment_config)
                EventManager.default().post_event_content(BehaviorEventKind.intersessionSegmentationError)
                self.end_analysis()

        self._segmentation_configuration = None

    def _detection_complete(self, nonce: str, success: bool):
        det_config = self._detection_configuration
        if det_config.nonce != nonce:
            logger.error("mismatched detection nonce: passed=%s cur_config=%s success=%s",
                         nonce, det_config, success)
            EventManager.default().post_event_content(BehaviorEventKind.intersessionDetectionNonceMismatch,
                                                      context=f"{det_config.nonce}:{nonce}")
            self.end_analysis()
        else:
            if not success:
                logger.error("perform detection failed. det_config=%s", det_config)
                EventManager.default().post_event_content(BehaviorEventKind.intersessionDetectionError)
            else:
                EventManager.default().post_event_content(BehaviorEventKind.intersessionDetectionEnd)

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
