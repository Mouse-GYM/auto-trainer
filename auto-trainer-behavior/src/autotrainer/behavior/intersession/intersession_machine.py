import secrets
from typing import Callable, Optional

from transitions import Machine

from autotrainer.core import ProjectInfo, EventManager, transitions_allow_functions
from . import IntersessionState
from ..behavior_event_kind import BehaviorEventKind

from ..inference_protocol import InferenceProtocol, SegmentationConfiguration, DetectionConfiguration
from ..behavior_algorithm import BehaviorAlgorithm
from ..state_machine import StateMachine, StateMachineEvents
from autotrainer.core.logging import get_verbose_logger

logger = get_verbose_logger(__name__)


class IntersessionMachineEvents(StateMachineEvents):
    on_analysis_started: Callable[[], None]
    on_analysis_ended: Callable[[], None]


class IntersessionMachine(StateMachine):
    _events_class = IntersessionMachineEvents

    states = [e for e in IntersessionState]

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
        self._segmentation_configuration: Optional[SegmentationConfiguration] = None
        self._detection_configuration: Optional[DetectionConfiguration] = None

    @property
    def project(self):
        return self._project_info

    @project.setter
    def project(self, project):
        self._project_info = project

    def after_enter_segmentation(self):
        prj = self._project_info
        segment_config = SegmentationConfiguration(nonce=secrets.token_hex(),
                                                   session_index=prj.session,
                                                   session_when=prj.when,
                                                   complete=lambda nonce, success:
                                                        self._segmentation_complete(nonce, success, segment_config=segment_config))
        self._segmentation_configuration = segment_config
        res = self._inference.perform_segmentation(segment_config)
        if res is None:
            logger.error("perform segmentation didn't started")
            self._segmentation_configuration = None
            self.end_analysis()
        else:
            self.events.on_analysis_started()  # should maybe conditioned by lower level lock too
            EventManager.default().post_event_content(BehaviorEventKind.intersessionSegmentationBegin,
                                                      context=segment_config.nonce)

    def after_enter_detection(self, segment_config: SegmentationConfiguration):
        detection_config = DetectionConfiguration(
            nonce=secrets.token_hex(),
            session_index=segment_config.session_index,
            session_when=segment_config.session_when,
            complete=lambda nonce, success: self._detection_complete(nonce, success, detection_config=detection_config),
        )
        res = self._inference.perform_detection(detection_config)
        if res is not None:
            self._detection_configuration = detection_config
            EventManager.default().post_event_content(BehaviorEventKind.intersessionDetectionBegin,
                                                      context=segment_config.nonce)

    def after_end_analysis(self):
        self.events.on_analysis_ended()
        self._segmentation_configuration = None
        self._detection_configuration = None

    def can_perform_segmentation(self):
        p = self._project_info is not None
        i = self._inference is not None
        s = self._segmentation_configuration is not None
        EventManager.default().post_event_content(
            BehaviorEventKind.intersessionSegmentationCan, context=f"{p}:{i}:{not s}")
        res = p and i and not s
        logger.debug("can_perform_segmentation=%s: prj=%s inference=%s segment=%s", res, p, i, s)
        return res

    def can_perform_detection(self, segment_config: Optional[SegmentationConfiguration] = None):
        p = self._project_info is not None
        i = self._inference is not None
        d = self._detection_configuration is None
        s = segment_config is not None
        EventManager.default().post_event_content(BehaviorEventKind.intersessionDetectionCan,
                                                  context=f"{p}:{i}:{d}:{s}")
        can_do_detection = p and i and d and s
        logger.debug("can_perform_detection=%s ; prj=%s inference=%s detection_config=%s segment_config=%s",
                    can_do_detection, p, i, d, s)
        return can_do_detection

    def _segmentation_complete(self, nonce: str, success: bool, *, segment_config: SegmentationConfiguration):
        if segment_config.nonce != nonce:
            # NB: should not happen anymore
            logger.error("mismatched segmentation nonce: passed=%s cur_seg_config=%s success=%s",
                         nonce, segment_config, success)
            EventManager.default().post_event_content(BehaviorEventKind.intersessionSegmentationNonceMismatch,
                                                      context=f"{segment_config.nonce}:{nonce}")
            self.end_analysis()
        else:
            if success:
                EventManager.default().post_event_content(BehaviorEventKind.intersessionSegmentationEnd)
                self.perform_detection(segment_config)
            else:
                logger.error("perform segmentation failed. config=%s", segment_config)
                EventManager.default().post_event_content(BehaviorEventKind.intersessionSegmentationError)
                self.end_analysis()

        self._segmentation_configuration = None

    def _detection_complete(self, nonce: str, success: bool, *, detection_config: DetectionConfiguration):
        if detection_config.nonce != nonce:
            # NB: should never happen anymore
            logger.error("mismatched detection nonce: passed=%s cur_config=%s success=%s",
                         nonce, detection_config, success)
            EventManager.default().post_event_content(BehaviorEventKind.intersessionDetectionNonceMismatch,
                                                      context=f"{detection_config.nonce}:{nonce}")
            self.end_analysis()
        else:
            if not success:
                logger.error("perform detection failed. det_config=%s", detection_config)
                EventManager.default().post_event_content(BehaviorEventKind.intersessionDetectionError)
            else:
                EventManager.default().post_event_content(
                    BehaviorEventKind.intersessionDetectionEnd,
                    context=f"nonce={detection_config.nonce};session_index={detection_config.session_index}")

            self.end_analysis()


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

    def perform_detection(self, segment_config):
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

    transitions = transitions_allow_functions([
        dict(
            trigger=perform_segmentation,
            source=IntersessionState.idle,
            dest=IntersessionState.segmentation,
            conditions=can_perform_segmentation,
            after=after_enter_segmentation,
        ),

        dict(
            trigger=perform_detection,
            source=IntersessionState.segmentation,
            dest=IntersessionState.detection,
            conditions=can_perform_detection,
            after=after_enter_detection,
        ),

        dict(
            trigger=end_analysis,
            source=[IntersessionState.segmentation, IntersessionState.detection],
            dest=IntersessionState.idle,
            after=after_end_analysis,
        ),
    ])
