import secrets
from functools import partial
from typing import Callable, Optional, get_type_hints

from transitions import Machine

from autotrainer.core import ProjectInfo, EventManager, transitions_allow_functions
from autotrainer.core import ApiEventKind as BehaviorEventKind

from . import IntersessionState
from .. import CaptureAnalysisResult

from ..inference_protocol import InferenceProtocol, SegmentationConfiguration, DetectionConfiguration
from ..behavior_algorithm import BehaviorAlgorithm
from ..state_machine import StateMachine, StateMachineEvents
from autotrainer.core.logging import get_verbose_logger

logger = get_verbose_logger(__name__)


class IntersessionMachineEvents(StateMachineEvents):
    on_analysis_started: Callable[[], None]  # unused
    on_analysis_ended: Callable[[CaptureAnalysisResult], None]


class IntersessionMachine(StateMachine):

    _events_class = IntersessionMachineEvents

    states = list(IntersessionState)

    def __init__(
        self,
        *,
        algorithm: BehaviorAlgorithm,
        inference: InferenceProtocol,
        project_info: ProjectInfo = None,
    ):

        initial_state = IntersessionState.idle

        super().__init__(initial_state=initial_state)

        self._machine = Machine(model=[self], states=IntersessionMachine.states,
                                transitions=IntersessionMachine.transitions, auto_transitions=False,
                                initial=initial_state, model_override=True)

        algorithm.relay_transitions(self)  # NB: must be done AFTER creation of previous machine instance

        self._project_info = project_info
        self._algorithm = algorithm
        self._inference = inference
        self._segmentation_configuration: Optional[SegmentationConfiguration] = None
        self._detection_configuration: Optional[DetectionConfiguration] = None

    @property
    def events(self) -> IntersessionMachineEvents:  # to have correct type hint as well
        return self._events

    @property
    def project(self):
        return self._project_info

    @project.setter
    def project(self, project: ProjectInfo):
        logger.verbose("project -> %s", project)
        self._project_info = project

    def reset_to_idle(self):
        self._detection_configuration = None
        self._segmentation_configuration = None
        self.state = IntersessionState.idle

    def after_enter_segmentation(self, project_info: ProjectInfo):
        segment_config = SegmentationConfiguration(
            nonce=secrets.token_hex(),
            session_index=project_info.session,
            session_when=project_info.when,
            project=project_info,
        )
        segment_config.complete = partial(self._segmentation_complete, segment_config=segment_config)
        self._segmentation_configuration = segment_config
        res = self._inference.perform_segmentation(segment_config)
        if res is None:
            logger.error("perform segmentation didn't started")
            self._segmentation_configuration = None
            self.end_analysis(False)
        else:
            self.events.on_analysis_started()
            self.post_event_content(BehaviorEventKind.intersessionSegmentationBegin,
                                    context=segment_config.nonce)

    def after_enter_detection(self, segment_config: SegmentationConfiguration):
        detection_config = DetectionConfiguration(
            nonce=secrets.token_hex(),
            session_index=segment_config.session_index,
            session_when=segment_config.session_when,
            project=segment_config.project,
        )
        detection_config.complete = partial(self._detection_complete, detection_config=detection_config)
        res = self._inference.perform_detection(detection_config)
        if res is not None:
            self._detection_configuration = detection_config
            self.post_event_content(BehaviorEventKind.intersessionDetectionBegin, context=segment_config.nonce)

    def after_end_analysis(self, success):
        self._segmentation_configuration = None
        self._detection_configuration = None
        result = CaptureAnalysisResult.ANALYSIS_SUCCEEDED if success else CaptureAnalysisResult.ANALYSIS_FAILED
        self._algorithm.end_session(result)
        self.events.on_analysis_ended(result)

    def can_perform_segmentation(self, project_info: ProjectInfo):
        p = project_info is not None
        i = self._inference is not None
        s = self._segmentation_configuration is None
        self.post_event_content(BehaviorEventKind.intersessionSegmentationCan, context=f"{p}:{i}:{s}")
        res = p and i and s
        logger.debug("can_perform_segmentation=%s: prj=%s inference=%s segment=%s",
                     res, p, i, s)
        return res

    def can_perform_detection(self, segment_config: SegmentationConfiguration):
        s = segment_config is not None  # always true
        p = segment_config.project is not None  # always true
        i = self._inference is not None
        d = self._detection_configuration is None
        self.post_event_content(BehaviorEventKind.intersessionDetectionCan,
                                                  context=f"{p}:{i}:{d}:{s}")
        can_do_detection = p and i and d and s
        logger.debug("can_perform_detection=%s ; prj=%s inference=%s detection_config=%s segment_config=%s",
                    can_do_detection, p, i, d, s)
        return can_do_detection

    def _segmentation_complete(self, nonce: str, success: bool, *, segment_config: SegmentationConfiguration):
        logger.verbose("segmentation_complete: nonce=%s success=%s config=%s",
                     nonce, success, segment_config)
        if segment_config.nonce != nonce:
            # NB: should not happen anymore
            logger.error("mismatched segmentation nonce: passed=%s cur_seg_config=%s success=%s",
                         nonce, segment_config, success)
            self.post_event_content(BehaviorEventKind.intersessionSegmentationNonceMismatch,
                                                      context=f"{segment_config.nonce}:{nonce}")
            self.end_analysis(False)
        else:
            if success:
                self.post_event_content(BehaviorEventKind.intersessionSegmentationEnd)
                if self.can_perform_detection(segment_config):  # must check, and if cannot must end_analysis
                    self.perform_detection(segment_config)
                else:
                    self.end_analysis(False)
            else:
                logger.error("perform segmentation failed. config=%s", segment_config)
                self.post_event_content(BehaviorEventKind.intersessionSegmentationError)
                self.end_analysis(False)

        self._segmentation_configuration = None

    def _detection_complete(self, nonce: str, success: bool, *, detection_config: DetectionConfiguration):
        if detection_config.nonce != nonce:
            # NB: should never happen anymore
            logger.error("mismatched detection nonce: passed=%s cur_config=%s success=%s",
                         nonce, detection_config, success)
            self.post_event_content(BehaviorEventKind.intersessionDetectionNonceMismatch,
                                                      context=f"{detection_config.nonce}:{nonce}")
            self.end_analysis(False)
        else:
            if not success:
                logger.error("perform detection failed. det_config=%s", detection_config)
                self.post_event_content(BehaviorEventKind.intersessionDetectionError)
            else:
                self.post_event_content(
                    BehaviorEventKind.intersessionDetectionEnd,
                    context=f"nonce={detection_config.nonce};session_index={detection_config.session_index}")

            self.end_analysis(success)

    # region State Machine Requirements
    # Methods required for model_override=True to work.
    def trigger(self):
        """Main trigger"""

    def may_trigger(self):
        """Main trigger"""

    def perform_segmentation(self, project_info: ProjectInfo):
        """Perform segmentation"""

    def may_perform_segmentation(self):
        """Perform segmentation"""

    def perform_detection(self, segment_config: SegmentationConfiguration):
        """Perform detection"""

    def may_perform_detection(self):
        """Perform detection"""

    def end_analysis(self, success: bool):
        """End analysis"""

    def may_end_analysis(self):
        """End analysis"""

    def is_idle(self):
        """Is idle"""

    def is_segmentation(self):
        """Is segmentation"""

    def is_detection(self):
        """Is detection"""
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
