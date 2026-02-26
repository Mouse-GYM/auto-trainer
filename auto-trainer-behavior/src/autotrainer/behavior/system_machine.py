import math
import time
from datetime import datetime
from functools import partial
from itertools import chain
from pathlib import Path
from typing import Optional, List

from transitions import Machine

from autotrainer.core import (ProjectInfo, EventManager, SensorAnalysis, LoadCellMonitor, Offset3DTuple,
                              HeadbarPressureMonitor, transitions_allow_functions, SystemMessageHandler, get_perf_now,
                              FrameIndexCategory)
from autotrainer.core import ApiEventKind as BehaviorEventKind

from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.pose_elements import SceneElement, AllHandsParts
from autotrainer.core.multiproc import make_daemon_timer, no_op_timer
from autotrainer.core.video_detection import PresenceDetectionAttrs
from autotrainer.core.analysis.detector import BaseDetector
from autotrainer.core.diamond_triangle_config import DiamondTriangleOffsetConfig

from autotrainer.inference import PoseResponse, InferenceStatus, InferenceCommandMessageKind, InferenceMonitorDataMsg
from autotrainer.inference.analysis import IntersessionResponse

from . import CaptureAnalysisResult, RecordingEndingReason
from .behavior_algorithm import BehaviorAlgorithm, BehaviorAlgoProps, BehaviorAlgoStatus
from .inference_protocol import InferenceProtocol
from .intersession import IntersessionMachine, IntersessionState
from .pellet import PelletState
from .pellet.pellet_machine import PelletMachine
from .pellet_device_protocol import PelletDeviceProtocol
from .state_machine import StateMachine
from .system_machine_state import SystemState
from .tunnel_device_protocol import TunnelDeviceProtocol


logger = get_verbose_logger(__name__)

# NB: this is to ensure we can patch the exact desired one (and only that one) from tests:
_clean_raw_data_timer = make_daemon_timer
_auto_clamp_release_timer = make_daemon_timer
_consider_start_session_timer = make_daemon_timer
_consider_end_session_timer = make_daemon_timer
_consider_auto_end_session_timer = make_daemon_timer
_check_missing_timer = make_daemon_timer
_consider_disengage_autoclamp_timer = make_daemon_timer
_consider_close_gate_timer = make_daemon_timer

#


class SystemMachine(StateMachine):

    states = list(SystemState)

    def __init__(self,
                 algorithm: Optional[BehaviorAlgorithm] = None,
                 project_info: Optional[ProjectInfo] = None,
                 msg_handler: SystemMessageHandler = None,
                 analysis: SensorAnalysis = None,
                 tunnel_device: TunnelDeviceProtocol = None,
                 pellet_device: PelletDeviceProtocol = None,
                 inference: InferenceProtocol = None,
                 topcam_presence: Optional[PresenceDetectionAttrs] = None,
                 ):

        initial_state = SystemState.cage
        super().__init__(initial_state=initial_state)

        self.machine = Machine(
            model=[self],
            states=self.states,
            transitions=self.transitions,
            auto_transitions=False,
            initial=initial_state,
            model_override=True,
        )

        self._project_info: Optional[ProjectInfo] = project_info
        self._batch_project_sessions_list: List[ProjectInfo] = []
        self._batch_processing_in_progress: bool = False
        self._batch_failed_count: int = 0
        self._batch_sessions_total_duration: float = 0

        self._timer_consider_start_session = no_op_timer
        self._timer_consider_end_session = no_op_timer
        self._timer_consider_auto_end_session = no_op_timer

        # TODO: should be moved to config somewhere:
        self._delay_timer_consider_end_session: float = 1
        # delay to wait, when/once a pellet load is executed (on start),
        # and that a session is active, to trigger an eventual end_session().
        # If 0 (or lower) : immediately consider end session on start of pellet-load.

        self._auto_clamp_in_progress = False
        self._auto_clamp_disengage_in_progress = False
        self._timer_consider_close_gate = no_op_timer
        self._timer_auto_clamp_evaluate = no_op_timer
        self._timer_auto_clamp_disengage = no_op_timer
        self._disengage_auto_clamp_load_count = 0
        self._last_disengage_autoclamp_perf_c = -math.inf

        self._last_close_tunnel_gate_perf_t = -math.inf
        self._is_handling_diamond_triangle = False

        self._enter_tunnel_pellet_seen = False

        self._session_started_perf_c = -math.inf

        self._tunnel_device = tunnel_device
        self._msg_handler = msg_handler

        self._algorithm: BehaviorAlgorithm = BehaviorAlgorithm(
            topcam_presence=topcam_presence,
        ) if algorithm is None else algorithm
        algo = self._algorithm
        del algorithm  # using algo
        algo.project = project_info
        algo.session_starting += self._session_capture_started
        algo.session_capture_ending += self._session_capture_ended
        algo.property_changed += self._algorithm_property_changed
        algo.relay_transitions(self)
        # NB: could use the shift_xyz_handler.property_changed callback handler with LAST_PROCESSED_SHIFT_XYZ name too:
        algo.shift_xyz_handler.set_processed_handler(self._handle_processed_shift_xyz)

        def sync_algo_system_state(_, new_state):
            self._algorithm.system_state = new_state
        self.events.state_changed += sync_algo_system_state
        algo.system_state = self._state  # to be sure

        self._analysis = analysis
        if analysis is not None:
            analysis.load_cell_monitor.property_changed += self._load_cell_monitor_property_changed
            analysis.headbar_pressure_monitor.property_changed += self._headbar_pressure_monitor_property_changed
            analysis.load_cell_tare_monitor.tare_callback = self._load_cell_tare_requested
            analysis.auto_tunnel_sweep_monitor.property_changed += self._auto_tunnel_sweep_property_changed
            # analysis.pellet_misplaced_monitor.dcs_config = algo.diamond_triangle_config
            #   handled by property changed.
            # set current configs from monitors:
            algo.active_config.auto_tunnel_sweep = analysis.auto_tunnel_sweep_monitor.config
            # analysis.pellet_misplaced_monitor.config  # not in system config for now

        self._inference = inference
        if inference is not None:
            inference.pose_response_ready += self._pose_changed
            inference.detection_result_ready += self._handle_detection_result
            inference.property_changed += self._handle_inference_property_changed
            inference.segmentation_finished += self._inference_segmentation_finished

        self._pellet_device = pellet_device

        pellet_machine = self._pellet_machine = PelletMachine(self.algorithm, msg_handler, pellet_device)
        pellet_machine.events.state_changed += self._pellet_state_changed
        pellet_machine.events.pellet_loading += self._pellet_loading
        pellet_machine.events.pellet_loaded += self._pellet_loaded
        pellet_machine.events.pellet_sent += self._pellet_sent

        intersession_machine = self._intersession = IntersessionMachine(algo, self._project_info, inference)
        intersession_machine.events.on_analysis_ended += self._intersession_analysis_ended
        intersession_machine.events.state_changed += self._intersession_state_changed
        algo.relay_transitions(intersession_machine)

    def cancel_timers(self):
        for timer in (
            self._timer_consider_start_session,
            self._timer_consider_end_session,
            self._timer_consider_auto_end_session,
            self._timer_consider_close_gate,
            self._timer_auto_clamp_disengage,
            self._timer_auto_clamp_evaluate,
        ):
            if not timer.finished.is_set():
                logger.debug("cancelling timer %s", timer)
                timer.cancel()
        self._timer_consider_start_session = no_op_timer
        self._timer_consider_end_session = no_op_timer
        self._timer_consider_close_gate = no_op_timer
        self._timer_auto_clamp_disengage = no_op_timer

    @property
    def analysis(self) -> SensorAnalysis:
        return self._analysis

    @property
    def algorithm(self) -> BehaviorAlgorithm:
        return self._algorithm

    @property
    def pellet(self) -> PelletMachine:
        return self._pellet_machine

    @property
    def intersession(self) -> IntersessionMachine:
        return self._intersession

    @property
    def project(self) -> ProjectInfo:
        return self._project_info

    @project.setter
    def project(self, value: ProjectInfo):
        self._project_info = value
        EventManager.default().project = value
        self._algorithm.project = value
        self._intersession.project = value

    def before_enter_tunnel(self, *, reason: str = "NA"):
        pellet_state = self._pellet_machine.state
        self._enter_tunnel_pellet_seen = self._algorithm.pellet_recently_seen
        logger.debug("before_enter_tunnel: reason=%s state=%s pellet_state=%s pellet_recently_seen=%s",
                     reason, self._state, pellet_state, self._enter_tunnel_pellet_seen)
        if self._state == SystemState.cage:
            # always when enter tunnel, but only if was in cage before.
            self._execute_disengage_auto_clamp_if_in_progress()
        EventManager.default().post_event_content(BehaviorEventKind.tunnelEnter)

    def after_enter_tunnel(self, *, reason: str = "NA"):
        self._consider_start_session(reason=reason)
        if self._analysis is not None:
            self._evaluate_auto_clamp()

    def after_exit_tunnel(self, *, reason: str = "NA"):
        logger.verbose("after_exit_tunnel: %s", reason)
        algo = self._algorithm
        self._timer_consider_start_session.cancel()
        self._timer_consider_end_session.cancel()
        self._disengage_auto_clamp()
        EventManager.default().post_event_content(BehaviorEventKind.tunnelExit)
        if algo.is_in_session:
            algo.end_capture_session(reason=RecordingEndingReason.EXIT_TUNNEL)
        else:
            if self._intersession.state == IntersessionState.idle and len(self._batch_project_sessions_list) > 0:
                self._inference.send_message(InferenceCommandMessageKind.ForceProcessOffline)
                self.enter_intersession(reason="exit-tunnel-with-sessions-batch-list")

    def after_enter_intersession(self, *, reason="NA"):
        logger.verbose("enter_intersession: reason=%s", reason)
        algo = self._algorithm
        intersession = self._intersession
        inference = self._inference
        batch_list = self._batch_project_sessions_list
        if len(batch_list) > 0:
            # set intersession and inference current project to the one from the batch:
            cur_prj = batch_list[0]
            intersession.project = cur_prj
            inference.project = cur_prj
            inference.put_to_data_handler(InferenceMonitorDataMsg.START_NEW_INTERSESSION_BATCH_ITEM)
            if not self._batch_processing_in_progress:
                self._batch_processing_in_progress = True
                self._batch_failed_count = 0
                logger.info("Starting batch analysis with %s trials", len(batch_list))
                algo.batch_analysis_starting(batch_len=len(batch_list))
        else:
            cur_prj = self._project_info.to_local_value()

        if self._pellet_machine.state == PelletState.monitoring:
            self._pellet_machine.move_retract()

        logger.info("processing session project %s", cur_prj)
        algo.session_processing_starting()

        intersession.perform_segmentation()
        self._consider_close_gate_during_intersession()

    def after_exit_intersession(self):
        if self._analysis.load_cell_monitor.is_engaged:
            self.exit_intersession_to_tunnel()
        else:
            # always ensure open gate on intersession ended (to cage)
            self._timer_consider_close_gate.cancel()
            self._tunnel_device.open_tunnel_gate()
            self._execute_disengage_auto_clamp_if_in_progress()
            self.exit_intersession_to_cage()

    def after_exit_intersession_to_cage(self):
        # ensure pellet goes back where necessary:
        self._pellet_machine.environment_changed(caller="exit_intersession_to_cage")

    def after_exit_intersession_to_tunnel(self):
        self.enter_tunnel(reason="exit_intersession_to_tunnel")

    @staticmethod
    def _clean_raw_data(project: ProjectInfo, *, wait_before_clean: float = 10):

        def do_clean():
            for cam_name in (project.camera_1, project.camera_2):
                paths = map(Path, chain(
                    project.get_video_path(cam_name, allow_overwrite=True),
                    [project.get_intersession_pose_path(cam_name, allow_overwrite=True, suffix="_live")],
                ))
                for path in paths:
                    if path.exists():
                        logger.debug("removing %s", path)
                        path.unlink(missing_ok=True)

        # using timer given when called the monitor data queue might still be writing to disk/still be in live session,
        # making the deletes to not work here
        t = _clean_raw_data_timer(wait_before_clean, do_clean)
        # changed timer to 15s: seen some cases where close of file handles in monitor data queue was bit slower,
        # and made some of the data files not be removed (given written to after).
        # if that still happens (like with overloaded system), then some files will be left on disk still.
        t.start()

    @BehaviorAlgorithm.relay_func(wait=False)
    def _consider_auto_end_session(self):
        self._timer_consider_auto_end_session.cancel()  # required
        algo = self._algorithm
        cfg = algo.auto_end_session_config
        if not algo.is_in_session or cfg is None or cfg.no_activity_delay_minutes <= 0:
            return
        mouse_seen_age = algo.mouse_seen_age  # reminder: this is the nose part which is accounted for mouse_seen
        in_session_age = algo.is_in_session_age
        if math.isinf(mouse_seen_age):
            last_activity_age = in_session_age
        else:
            last_activity_age = min(mouse_seen_age, in_session_age)
        remains = 60 * cfg.no_activity_delay_minutes - last_activity_age
        if remains <= 0:
            algo.end_capture_session(reason=RecordingEndingReason.MISSING_ANIMAL_ACTIVITY_TIMEOUT)
        else:
            logger.info("started new timer for consider_auto_end_session in %.1fs", remains)
            timer = self._timer_consider_auto_end_session = _consider_auto_end_session_timer(
                remains, self._consider_auto_end_session
            )
            timer.start()

    @BehaviorAlgorithm.relay_func(wait=False)
    def _session_capture_started(self):
        self._session_started_perf_c = get_perf_now()
        # ensure inference has the correct project info,
        # this is required for session batch processing.
        self._inference.project = self._project_info
        self._intersession.project = self._project_info  # same for intersession
        self._consider_auto_end_session()  # this will postpone the auto-end of the needed delay

    @BehaviorAlgorithm.relay_func(wait=False)
    def _session_capture_ended(self, reason: RecordingEndingReason):
        self._timer_consider_auto_end_session.cancel()
        if reason == RecordingEndingReason.MISSING_ANIMAL_ACTIVITY_TIMEOUT:
            logger.notice("Forcing tare load cell due to %s", reason)
            self._tunnel_device.tare_load_cell()
        p_now = get_perf_now()
        self._batch_sessions_total_duration += p_now - self._session_started_perf_c
        cur_project = self.project
        if cur_project is not None:
            cur_project = cur_project.to_local_value()
        algo = self.algorithm
        #
        can_perform_analysis = (
            cur_project is not None
            and algo.can_perform_intersession_analysis()
            and self._intersession.can_perform_segmentation()
        )
        real_can_perform_analysis = can_perform_analysis
        can_batch_session = False
        cur_sessions_batch = self._batch_project_sessions_list
        batch_sess_cfg = algo.batch_session_recording_config
        load_cell_engaged = self._analysis.load_cell_monitor.is_engaged
        if can_perform_analysis:
            if batch_sess_cfg.enabled or len(cur_sessions_batch) > 0:
                # > 0:  in case it's disabled while there is some session(s) currently batched
                cur_sessions_batch.append(cur_project)
                if 0 < batch_sess_cfg.maximum_batch_size <= len(cur_sessions_batch):
                    logger.verbose("reached maximum_batch_size, doing batch-intersession analysis")
                elif not load_cell_engaged:
                    logger.verbose("load-cell disengaged, doing batch-intersession analysis")
                elif not batch_sess_cfg.enabled:
                    logger.verbose("batch disabled, doing batch-intersession analysis")
                else:
                    logger.info("added session %s to current batch list len=%s", cur_project, len(cur_sessions_batch))
                    can_batch_session = True
                    can_perform_analysis = False
        else:
            can_batch_session = (
                load_cell_engaged
                and batch_sess_cfg.enabled  #  or len(cur_sessions_batch) > 0
            )
        #
        logger.notice(
            "session ended: intersession.state=%s system_machine.state=%s algo.system_state=%s "
            "pellet_machine.state=%s intersession_enabled=%s session_mouse_seen=%s "
            "can_batch=%s can_perform_analysis=%s real=%s",
            self._intersession.state, self.state, algo.system_state,
            self._pellet_machine.state,
            algo.intersession_enabled, algo.session_mouse_seen,
            can_batch_session, can_perform_analysis, real_can_perform_analysis,
        )
        # first:
        if (    not can_perform_analysis
            and not can_batch_session
            and not algo.session_mouse_seen
            and cur_project is not None
        ):
            if algo.clean_raw_data_on_inactive_session:
                self._clean_raw_data(cur_project)
        #
        if (can_perform_analysis or len(cur_sessions_batch) > 0) and not can_batch_session:
            if len(cur_sessions_batch) == 1 and self._project_info == cur_sessions_batch[0]:
                logger.debug("only 1 session in batch, skipping batch")
                # no need if it's the latest/current project-session-info already.
                cur_sessions_batch.clear()
                # it will be handled normally anyway
            self.enter_intersession(reason="capture-ended-and-can-perform-analysis")
        else:
            self._inference.put_to_offline_queue(FrameIndexCategory.SWITCH_TO_ONLINE, reason='session_capture_ended')
            algo.end_session(CaptureAnalysisResult.ANALYSIS_DELAYED if real_can_perform_analysis
                             else CaptureAnalysisResult.CAPTURE_ONLY)

    @BehaviorAlgorithm.relay_func(wait=False)
    def _intersession_analysis_ended(self, result: CaptureAnalysisResult):
        logger.verbose("intersession ended: result=%s prj=%s", result, self._intersession.project)
        cur_batch = self._batch_project_sessions_list
        if len(cur_batch) > 0:
            del cur_batch[0]
            if result == CaptureAnalysisResult.ANALYSIS_FAILED:
                self._batch_failed_count += 1
            if len(cur_batch) > 0:  #  and not self._algorithm.algo_paused:
                # continue remaining session(s) in batch in all cases
                self.reenter_intersession(reason="reenter-batch-session")
                return
            self._batch_processing_in_progress = False
            self._batch_sessions_total_duration = 0
            logger.info("batch analysis ending, failed=%s", self._batch_failed_count)
            # force intersession & inference project-info back to current/live one:
            self._intersession.project = self._project_info
            self._inference.project = self._project_info
            self._algorithm.batch_analysis_ending(failed_count=self._batch_failed_count)

        self.exit_intersession()

    @BehaviorAlgorithm.relay_func(wait=False)
    def _handle_inference_property_changed(self, name: str, new_value, prev_value):
        if name == InferenceProtocol.STATUS:
            logger.verbose("Inference status change: %s -> %s ; system_state=%s",
                           prev_value, new_value, self.state)
            self._consider_enter_tunnel(reason="inference_begin_live_when_load_cell_engaged")

    def _inference_segmentation_finished(self, success):
        logger.verbose("got inference segmentation finished: %s", success)
        inference = self._inference
        inference.put_to_offline_queue(FrameIndexCategory.EOF_OFFLINE_PROCESSING, reason='segmentation_finished')
        cur_batch_list = self._batch_project_sessions_list
        logger.debug("cur_batch_list=%s", cur_batch_list)
        if len(cur_batch_list) <= 1:
            inference.put_to_offline_queue(FrameIndexCategory.SWITCH_TO_ONLINE, reason='segmentation_finished')

    @BehaviorAlgorithm.relay_func(wait=False)
    def _headbar_pressure_monitor_property_changed(self, name: str, value, _):
        # if self._state == SystemState.intersession:
        #     logger.info("ignoring headbar pressure property changed while intersession")
        #     # TODO new need event kind
        #     # EventManager.default().post_event(BehaviorEventKind.headfixLoadCellChangedInIntersession, context=value)
        #     # but don't we want this in evaluate_auto_clamp() itself ?
        #     return

        if name == HeadbarPressureMonitor.IS_ENGAGED_PROPERTY:
            EventManager.default().post_event_content(BehaviorEventKind.headFixationForceDetectorChanged, context=value)
            if value:
                self._evaluate_auto_clamp()

    @BehaviorAlgorithm.relay_func(wait=False)
    def _load_cell_monitor_property_changed(self, name: str, value, _):
        if self._state == SystemState.intersession:
            EventManager.default().post_event_content(BehaviorEventKind.headfixLoadCellChangedInIntersession,
                                                      context=value)
            # return
            # allow following code still, we want it always. it's checking state furthermore.

        if name == LoadCellMonitor.IS_ENGAGED_PROPERTY:
            EventManager.default().post_event_content(BehaviorEventKind.headfixLoadCellChanged, context=value)
            if value:
                self._analysis.global_animal_presence_monitor.stop()
                self._consider_enter_tunnel(reason="load_cell_engaged_when_in_cage")
            else:
                if self._inference.status == InferenceStatus.live:
                    self._analysis.global_animal_presence_monitor.start()
                inter_state = self.intersession.state
                if self._state != SystemState.cage:
                    if inter_state == IntersessionState.idle:
                        self.exit_tunnel(reason="load_cell_disengaged_intersession_idle")
                    else:
                        # this does same than exit_tunnel, without updating the current state,
                        # which is either segmentation or detection
                        self.after_exit_tunnel(reason="load_cell_disengaged_intersession_in_progress")
                        # logger.verbose("skipping exit_tunnel due to intersession still in progress: %s", inter_state)
                else:
                    EventManager.default().post_event_content(BehaviorEventKind.headfixLoadCellChangedWrongState,
                                                              context=self._state)

    @BehaviorAlgorithm.relay_func(wait=False)
    def _evaluate_auto_clamp(self):
        algo = self._algorithm
        if algo.algo_paused:
            logger.debug("auto_clamp: algo-paused, skipping evaluate")
            return
        if self._auto_clamp_in_progress:
            logger.debug("auto_clamp already in progress")
            return
        is_headbar_pressure_engaged = self._analysis.headbar_pressure_monitor.is_engaged
        self._timer_auto_clamp_evaluate.cancel()  # in case of
        self._timer_auto_clamp_disengage.cancel()  # also
        self._timer_auto_clamp_evaluate = no_op_timer
        if not algo.head_fixation_enabled:
            logger.info("auto-clamp: disabled (no action taken)")
            return
        if not self._analysis.load_cell_monitor.is_engaged:
            logger.info("auto-clamp: load-cell not engaged (no action taken)")
            return
        if not is_headbar_pressure_engaged:
            logger.info("auto-clamp: detector not engaged (no action taken)")
            return
        p_now = get_perf_now()
        disengage_age = p_now - self._last_disengage_autoclamp_perf_c
        remains = algo.auto_clamp_before_reengage_delay - disengage_age
        if remains > 0:
            logger.verbose("delaying evaluate auto-clamp in %.1fs due to recent disengage ; age=%.1fs",
                         remains, disengage_age)
            timer = make_daemon_timer(remains, self._evaluate_auto_clamp)
            self._timer_auto_clamp_evaluate = timer
            timer.start()
            return
        algo = self._algorithm
        logger.info("auto-clamp setting position to %s", algo.auto_clamp_intensity)
        self._auto_clamp_in_progress = True
        self._update_magnet_position(algo.auto_clamp_intensity)
        self._disengage_auto_clamp_load_count = 0
        self._timer_auto_clamp_disengage.cancel()  # in case of
        t_delay = algo.auto_clamp_no_activity_release_delay
        if t_delay > 0:
            logger.debug("starting new timer for disengage_auto_clamp in %.2f seconds", t_delay)
            new_timer = self._timer_auto_clamp_disengage = _consider_disengage_autoclamp_timer(
                t_delay, self._disengage_auto_clamp,
            )
            new_timer.start()
        EventManager.default().post_event_content(BehaviorEventKind.headFixationEnabled)

    @BehaviorAlgorithm.relay_func
    def _load_cell_tare_requested(self):
        if not self._analysis.load_cell_monitor.is_engaged:
            self._tunnel_device.tare_load_cell()
            EventManager.default().post_event_content(BehaviorEventKind.headfixAutoTare)
        return False

    def _evaluate_home_on_excessive_drift(self):
        # might be todo: convert to a detector
        algo = self._algorithm
        home_on_drift_cfg = algo.home_on_excessive_drift_distance_config
        nb_points = algo.diamond_triangle_drift_data_points_size
        #
        if not (
            home_on_drift_cfg.enabled
            and nb_points >= home_on_drift_cfg.min_samples
        ):
            return
        # also reset if distance is good,
        # so that we'll have to get min_samples data point before next check
        cur_drift = algo.get_diamond_triangle_drifts(reset=True, show_log=False)
        drift_dist = math.nan if cur_drift is None else cur_drift.distance
        if math.isnan(drift_dist) or drift_dist < home_on_drift_cfg.excessive_distance_threshold:
            return
        logger.notice("Measured motor drift too high (%.1fmm), executing home procedure",
                      drift_dist)
        self._pellet_machine.move_home()
        if algo.is_in_session:
            algo.end_capture_session(reason=RecordingEndingReason.MOTOR_DRIFT_HOMING)

    # @BehaviorAlgorithm.relay_func(wait=False)
    # not needed, already called by _pose_changed which has already it.
    def _handle_diamond_triangle_offset_changed(self, offset: Optional[Offset3DTuple]):
        if offset is None:
            return
        algo = self._algorithm
        if (
            # self._state == SystemState.tunnel
            # TODO: we could also decide to check in SystemState.cage as well,
            #  as far as we can ensure pellet is at deliver/send position
            self._pellet_machine.state == PelletState.monitoring
            and self._pellet_machine.can_use_pellet_command()
        ):
            last_pos = self._pellet_device.last_position
            if last_pos is not None:
                if not self._is_handling_diamond_triangle:
                    self._is_handling_diamond_triangle = True
                    logger.info("Starting handling diamond-triangle offset ; current offset=%s pos=%s",
                                offset.humanize(), last_pos.humanize())
                    # ensure we get refreshed data:
                    algo.get_diamond_triangle_drifts(reset=True, show_log=False)
                    # don't show log, to not show most likely bad value due to previous motor move
                algo.handle_diamond_triangle_offset(offset, last_pos)
                # if not algo.is_in_session:
                self._evaluate_home_on_excessive_drift()
        else:
            if self._is_handling_diamond_triangle:
                self._is_handling_diamond_triangle = False
                algo.get_diamond_triangle_drifts(show_log=True)

    def _handle_triangle_pellet_offset_changed(self, offset: Optional[Offset3DTuple]):
        if offset is None:  # not sure we should not let it pass to algo
            return
        self._algorithm.triangle_pellet_offset = offset

    def _handle_star_triangle_offset_changed(self, offset: Optional[Offset3DTuple]):
        if offset is None:
            return
        pellet_machine = self._pellet_machine
        if not pellet_machine.can_use_pellet_command():
            # never consider any release or cover check when pellet cannot be used yet.
            return
        algo = self._algorithm
        # only check cover if not in session and pellet covered state is True (== covered) and in monitoring
        check_cover_distance = not algo.is_in_session and (
            (pellet_machine.state == PelletState.monitoring
             and pellet_machine.covered_state is True)
        )
        if check_cover_distance:
            algo.handle_cover_pellet_offset(offset)
            # ofc never consider the check release position when we checked the cover one
            return
        # otherwise, given can_use_pellet_command() is True (check above),
        # we know we have to check release pos distance if state is monitoring and covered state is False ( == released)
        check_release_distance = (
            pellet_machine.state == PelletState.monitoring
            and pellet_machine.covered_state is False
        )
        if check_release_distance:
            algo.handle_release_pellet_offset(offset)

    def _handle_pellet_hands_offsets(self, response: PoseResponse):
        algo = self._algorithm
        min_dist = math.inf
        for part in (SceneElement.L_Hand, SceneElement.R_Hand):
            offset = response.get_parts_3d_offset(SceneElement.Pellet, part)
            if offset is not None:
                dist = offset.distance
                if dist < min_dist:
                    min_dist = dist
        algo.pellet_hands_min_distance = min_dist
        if __debug__:
            prev_dist = getattr(self, "_prev_pellet_hands_dist", math.inf)
            if f"{prev_dist:.0f}" != f"{prev_dist:.0f}":
                logger.spam("pellet_hands min distance: %.3f -> %.3f", prev_dist, min_dist)
            self._prev_pellet_hands_dist = min_dist
        #
        # already handled by _algorithm_property_changed with HANDS_NEAR_PELLET_SEEN
        # if algo.hands_near_pellet_seen and not prev_hands_seen_near_pellet:
        #     self._pellet_machine.environment_changed(caller="hands_seen_near_pellet")

    @BehaviorAlgorithm.relay_func(wait=False)
    def _pose_changed(self, response: PoseResponse):
        if __debug__:
            t_last = getattr(self, "_last_pose_changed_logged", 0)
            p_now = get_perf_now()
            if p_now - t_last >= 30:
                logger.debug("pose_changed: %s", response)
                self._last_pose_changed_logged = p_now
        #
        pellet_3d = response.locations_3d.get(SceneElement.Pellet)
        self._analysis.pellet_misplaced_monitor.update(pellet_3d)

        #
        self._handle_diamond_triangle_offset_changed(
            response.get_parts_3d_offset(SceneElement.Diamond, SceneElement.Triangle))

        self._handle_star_triangle_offset_changed(
            response.get_parts_3d_offset(SceneElement.Star, SceneElement.Triangle))

        self._handle_triangle_pellet_offset_changed(
            response.get_parts_3d_offset(SceneElement.Triangle, SceneElement.Pellet))
        #
        algo = self._algorithm
        if algo.is_in_session and not algo.session_mouse_seen and response.mouse_seen:
            logger.success("session first mouse_seen: parts=%s locations=%s", response.parts_flags, response.locations)
        #
        prev_pellet_seen = algo.pellet_recently_seen
        #
        algo.update_triangle_seen(response.triangle_seen)
        algo.update_diamond_seen(response.diamond_seen)
        algo.update_star_seen(response.star_seen)
        algo.update_pellet_seen(response.pellet_seen)
        algo.update_mouse_seen(response.mouse_seen)
        #
        if not prev_pellet_seen and response.pellet_seen and (
            self._state == SystemState.tunnel
            and not algo.is_in_session
            and self._analysis.load_cell_monitor.is_engaged
            and self._pellet_machine.state == PelletState.monitoring
        ):
            # this is mainly for when app/acquisition starts :
            # if load-cell is engaged before inference is live then we need this case/if.
            self._consider_start_session(reason="first-pellet-seen")
        #
        self._handle_pellet_hands_offsets(response)
        self._pellet_machine.pellet_seen(response.pellet_seen)

    # AUTO-CLAMP / HEAD-BAR

    @BehaviorAlgorithm.relay_func(wait=False)
    def _execute_disengage_auto_clamp_if_in_progress(self):
        self._timer_auto_clamp_evaluate.cancel()  # in case of
        self._timer_auto_clamp_disengage.cancel()  # better needed
        if not self._auto_clamp_in_progress:
            return
        baseline_intensity = self._algorithm.baseline_intensity
        logger.info("Disengaging auto-clamp to intensity %s", baseline_intensity)
        self._last_disengage_autoclamp_perf_c = get_perf_now()
        self._update_magnet_position(baseline_intensity)
        self._auto_clamp_in_progress = False
        self._auto_clamp_disengage_in_progress = False

    @BehaviorAlgorithm.relay_func(wait=False)
    def _pre_disengage_auto_clamp(self):
        clamp_cfg = self._algorithm.head_clamp_config
        self._timer_auto_clamp_evaluate.cancel()  # in case of
        self._timer_auto_clamp_disengage.cancel()  # also
        pre_duration = clamp_cfg.prerelease_duration
        if pre_duration > 0:
            logger.verbose("setting head-clamp to pre-release intensity %s", clamp_cfg.prerelease_intensity)
            self._update_magnet_position(clamp_cfg.prerelease_intensity)
            logger.debug("started timer for really disengage auto-clamp in %.1fs", pre_duration)
            timer = self._timer_auto_clamp_disengage = _auto_clamp_release_timer(
                pre_duration, self._execute_disengage_auto_clamp_if_in_progress
            )
            timer.start()
        else:
            self._execute_disengage_auto_clamp_if_in_progress()

    @BehaviorAlgorithm.relay_func(wait=False)
    def _disengage_auto_clamp(self):
        if not self._auto_clamp_in_progress:
            logger.debug("skipping disengage auto-clamp if not in progress")
            return
        if self._auto_clamp_disengage_in_progress:
            logger.debug("skipping new disengage while disengage already in progress")
            return
        self._auto_clamp_disengage_in_progress = True
        logger.info("auto-clamp: starting disengage procedure..")
        self._timer_auto_clamp_evaluate.cancel()  # in case of
        self._timer_auto_clamp_disengage.cancel()  # also
        pellet_dev = self._pellet_device
        algo = self._algorithm
        clamp_cfg = algo.head_clamp_config
        if algo.is_in_session:
            freq = clamp_cfg.auto_clamp_release_tone_freq
            logger.debug("sending tone (freq=%s) to indicate auto-clamp disabled", freq)
            pellet_dev.play_tone(freq, 0.5)
        after_tone_delay = algo.auto_clamp_release_tone_delay
        if after_tone_delay > 0:
            logger.debug(
                "changing magnet to baseline intensity in %.2f seconds", after_tone_delay)
            timer = self._timer_auto_clamp_disengage = _auto_clamp_release_timer(
                after_tone_delay,
                self._pre_disengage_auto_clamp,
            )
            timer.start()
        else:
            self._pre_disengage_auto_clamp()

    @BehaviorAlgorithm.relay_func(wait=False)
    def _consider_close_gate_during_intersession(self):
        self._timer_consider_close_gate.cancel()  # always
        algo = self._algorithm
        close_cfg = algo.auto_close_gate_on_intersession_config
        if not close_cfg.enabled:
            logger.debug("auto_close_gate disabled, skipping auto-close-gate")
            return
        topcam_pres = algo.top_camera_presence_detection
        if topcam_pres is None:
            logger.warning("topcam presence not enabled, forced skipping auto-close-gate")
            return
        if algo.algo_paused:
            logger.debug("algo disabled, skipping auto-close-gate")
            return
        if self._state != SystemState.intersession:
            logger.debug("not anymore intersession, skipping auto-close-gate")
            return
        duration = self._batch_sessions_total_duration
        if duration < close_cfg.session_min_duration:
            logger.debug("session duration too short, skipping auto-close-gate")
            return
        load_cell_mon = self._analysis.load_cell_monitor.context
        auto_close_gate_cfg = algo.auto_close_gate_on_intersession_config
        perf_now = get_perf_now()
        if (
            not load_cell_mon.is_engaged
            and topcam_pres.last_presence_start_perf_c >= load_cell_mon.last_disengaged_perf_c
            # ensure load-cell is not re-entered by the mouse:
            and topcam_pres.last_presence_start_perf_c > load_cell_mon.last_engaged_perf_c
            and perf_now - topcam_pres.last_presence_start_perf_c > close_cfg.delay_after_cage_enter
        ):
            logger.notice(
                "Closing tunnel gate for intersession ;"
                " perf_now=%.1f load_cell.last_disengaged=%.1f last_engaged=%.1f topcam.last_pres=%.1f",
                perf_now, load_cell_mon.last_disengaged_perf_c, load_cell_mon.last_engaged_perf_c,
                topcam_pres.last_presence_start_perf_c,
            )
            self._tunnel_device.close_tunnel_gate()
        else:
            # retry:
            delay = min(
                1.0,
                max(0.1,
                    auto_close_gate_cfg.delay_after_cage_enter - (perf_now - topcam_pres.last_presence_start_perf_c))
            )
            # logger.debug("starting timer for consider_close_gate in %.1fs", delay)
            timer = self._timer_consider_close_gate = _consider_close_gate_timer(
                delay, self._consider_close_gate_during_intersession)
            timer.start()

    @BehaviorAlgorithm.relay_func(wait=False)
    def _algorithm_property_changed(self, name: str, new_value, _):
        # Always back off to the baseline intensity when auto-clamp is disabled.
        pellet_dev = self._pellet_device
        props = BehaviorAlgoProps
        #
        if name == props.HEAD_FIXATION_ENABLED:
            if not new_value:
                logger.debug("auto-clamp disabled (backing off to baseline intensity)")
                self._disengage_auto_clamp()
                # todo: don't we want : self._execute_disengage_auto_clamp() ?

        elif name == props.AUTO_CORRECT_MOTOR_DRIFT:
            pellet_dev.set_auto_correct_motor_drift(new_value)

        elif name == props.HANDS_NEAR_PELLET_SEEN:
            if new_value:  # not interrested when reset to False
                self._pellet_machine.environment_changed(must_release=new_value)

        elif name == props.ALGO_PAUSED:
            algo = self._algorithm
            tunnel_dev = self._tunnel_device
            self.cancel_timers()
            # don't leave in-progress:
            self._auto_clamp_in_progress = self._auto_clamp_disengage_in_progress = False
            if new_value:
                if algo.is_in_session:
                    if algo.intersession_state == IntersessionState.idle:
                        algo.end_capture_session(reason=RecordingEndingReason.ALGO_PAUSED)
                tunnel_dev.open_tunnel_gate()
                self._update_magnet_position(0)
                # self._pellet_machine.move_home()  # pellet_machine is disabled once algo_paused is set.
                # so directly call the device command:
                pellet_dev.send_home()
            else:
                tunnel_dev.open_tunnel_gate()
                self._update_magnet_position(algo.baseline_intensity)
                pellet_dev.send_pellet()
                #
                # trigger load cell property changed check, so that new session will be started if mouse still in tunnel
                self._load_cell_monitor_property_changed(
                    LoadCellMonitor.IS_ENGAGED_PROPERTY, self._analysis.load_cell_monitor.is_engaged, None
                )
                # also trigger others checks:
                self._handle_inference_property_changed(InferenceProtocol.STATUS, self._inference.status, None)

        elif name == props.DIAMOND_TRIANGLE_CONFIG:
            self._analysis.pellet_misplaced_monitor.dcs_config = new_value

    def _auto_tunnel_sweep_property_changed(self, name, value, _):
        if name == BaseDetector.IS_ENGAGED:
            if value:
                self._pellet_device.set_tunnel_fan_on()
            else:
                self._pellet_device.set_tunnel_fan_off()

    def _update_magnet_position(self, position: float):
        self._tunnel_device.update_head_magnet_intensity(position)

    @BehaviorAlgorithm.relay_func(wait=False)
    def _pellet_loading(self):
        algo = self._algorithm

        self._timer_consider_start_session.cancel()  # we will get a pellet_loaded event once it's finished

        self._disengage_auto_clamp_load_count += 1
        if self._disengage_auto_clamp_load_count >= algo.auto_clamp_release_load_count:
            self._disengage_auto_clamp()

        if algo.is_in_session and self._state != SystemState.intersession:
            self._consider_end_session(reason=RecordingEndingReason.PELLET_LOADING)

    def _pellet_loaded(self):
        self._algorithm.pellet_loaded()

    def _pellet_state_changed(self, old_value, new_value):
        logger.info("pellet_state_changed: %s -> %s", old_value, new_value)
        if new_value == PelletState.monitoring:
            self._consider_start_session(reason="pellet-monitoring")

    def _intersession_state_changed(self, old_value, new_value):
        self._algorithm.intersession_state = new_value

    def _pellet_sent(self):
        self._consider_start_session(reason="pellet-sent")

    def _consider_enter_tunnel(self, reason: str="NA"):
        if not (
            self._state == SystemState.cage
            and self._inference.status == InferenceStatus.live
            and not self._algorithm.algo_paused
            and self._analysis.load_cell_monitor.context.is_engaged
        ):
            return
        self.enter_tunnel(reason=reason)

    @BehaviorAlgorithm.relay_func(wait=False)
    def _consider_start_session(self, reason: str = "NA"):
        self._timer_consider_start_session.cancel()  # in case of
        self._timer_consider_start_session = no_op_timer
        algo = self._algorithm
        if algo.algo_paused:
            return
        if algo.status != BehaviorAlgoStatus.ANIMAL_IN_TRAINING:
            return
        perf_now = get_perf_now()
        pellet_seen_age = algo.pellet_seen_age
        pellet_machine = self._pellet_machine
        send_begin_age = pellet_machine.get_pellet_send_begin_age(perf_now)
        send_end_age = pellet_machine.get_pellet_send_end_age(perf_now)
        logger.verbose(
            "consider_start_session: load_cell.engaged=%s "
            "state=%s pellet-state=%s recently_seen=%s seen_age=%.1f in_session=%s "
            "send_begin_age=%.1f send_end_age=%.1f capture_status_age=%.1f",
            self._analysis.load_cell_monitor.is_engaged,
            self._state, self._pellet_machine.state, algo.pellet_recently_seen, pellet_seen_age,
            algo.is_in_session, send_begin_age, send_end_age, algo.capture_status_age)
        # NB/TODO: maybe we should consider if pellet was seen and disappeared before we start the session,
        # to still start it : a mouse could be in tunnel, and pellet move back from load-pellet and mouse hit/makes
        # the pellet to fall or get it, before we got the time to notice it here..
        if not (
            self._state == SystemState.tunnel
            and not algo.is_in_session
            and self._analysis.load_cell_monitor.is_engaged
            and pellet_machine.state == PelletState.monitoring
            # waiting monitoring state, ensure pellet is in deliver position
        ):
            logger.debug("Not good state")
            return
        if not math.isinf(send_begin_age) and send_begin_age < send_end_age:
            logger.debug("Wait pellet is sent")
            # wait pellet-sent, no need further timer:
            # we'll get a pellet_machine.events.pellet_sent() when it's received/acked
            return
        if not algo.pellet_recently_seen:
            logger.debug("Wait pellet seen")
            # pellet not seen, if enabled a pellet-load will be executed,
            # which we also consider-start-session for it.
            return
        #
        if math.isinf(send_begin_age) and math.isinf(send_end_age):
            remains = 0  # first session
        else:
            # This ensures that we'll have the start of video matching the very end, or ~right after,
            # of send-pellet action/move.
            remains = algo.record_prebuffer_duration - send_end_age
        if remains > 0:
            logger.verbose("Starting timer for consider_start_session in %.1f secs (record_prebuffer)", remains)
            timer = _consider_start_session_timer(
                remains, lambda: self._consider_start_session(reason=reason))
            self._timer_consider_start_session = timer
            timer.start()
            return
        algo.start_session(reason=reason)

    @BehaviorAlgorithm.relay_func(wait=False)
    def _consider_end_session(self, *, reason: RecordingEndingReason = RecordingEndingReason.NA):
        algo = self._algorithm
        if not algo.is_in_session:
            logger.debug("_consider_end_session: reason=%s but not in session ; state=%s pellet=%s",
                         reason, self._state, self._pellet_machine.state)
            return
        delay = self._delay_timer_consider_end_session
        if delay > 0:
            prev_timer = self._timer_consider_end_session
            # check if there is not an eventual previous timer not finished,
            # in case timer delay is greater than load duration and that many load-pellet happens due
            # to missed load.
            if prev_timer.finished.is_set():
                timer = self._timer_consider_end_session = _consider_end_session_timer(
                    delay, lambda: algo.end_capture_session(reason=reason))
                timer.start()
        else:
            algo.end_capture_session(reason=reason)

    @BehaviorAlgorithm.relay_func(wait=False)
    def _handle_detection_result(self, prj: ProjectInfo, res: IntersessionResponse):
        logger.success("Intersession analysis result: prj=%s result=%s", prj, res)
        #
        algo = self._algorithm
        if res.food_consumed > 0:
            algo.increase_pellets_consumed(res.food_consumed)
        if res.successful_reaches > 0:
            algo.increase_successful_reaches(res.successful_reaches)
        if res.pellets_presented > 0:
            algo.increase_pellets_presented(res.pellets_presented)
        algo.pellet_reaches_day += res.total_reaches
        algo.pellet_reaches_total += res.total_reaches
        #
        algo.shift_xyz_handler.put_intersession_response(res)

    def _handle_processed_shift_xyz(self, shift_xyz: Offset3DTuple):
        logger.success("Received processed shift xyz: %s", shift_xyz.round(1))
        dev = self._pellet_device
        algo = self.algorithm
        if dev is None or not algo.intersession_pellet_shift_enabled:
            return
        # flips are at the moment statics, but handle possible custom flips ; defensive:
        cfg = DiamondTriangleOffsetConfig if algo.diamond_triangle_config is None else algo.diamond_triangle_config
        # NB: dev.set_x/y/z is in motor coordinate system,
        # but we want the shifts to be in inference system :
        for idx, (val, meth, kind) in enumerate((
            (shift_xyz[0], dev.set_x, BehaviorEventKind.intersessionShiftX),
            (shift_xyz[1], dev.set_y, BehaviorEventKind.intersessionShiftY),
            (shift_xyz[2], dev.set_z, BehaviorEventKind.intersessionShiftZ)),
        ):
            if val != 0:
                val *= cfg.flips_motor_diamond[idx]
                logger.debug("applying %s with shift: %.1f", kind, val)
                token = meth(val, absolute=False, sender="processed_shift_xyz")
                if token is None:
                    logger.error("Could not apply %s ; command not successfull", kind)
                EventManager.default().post_event_content(kind, context=val)
            else:
                logger.debug("%s == 0 ; skip", kind)

    # region State Machine Requirements
    # Methods required for model_override=True to work.
    def trigger(self):
        """Trigger"""

    def may_trigger(self):
        """Trigger"""

    def enter_tunnel(self, *, reason: str = "NA"):
        """Enter tunnel"""

    def may_enter_tunnel(self):
        """Enter tunnel"""

    def exit_tunnel(self, *, reason: str = "NA"):
        """Exit tunnel"""

    def may_exit_tunnel(self):
        """Exit tunnel"""

    def enter_intersession(self, *, reason: str="NA"):
        """Enter intersession"""

    def may_enter_intersession(self):
        """May Enter intersession"""

    def reenter_intersession(self, *, reason: str="NA"):
        """ReEnter intersession (from previous intersession)"""

    def may_reenter_intersession(self):
        """May ReEnter intersession"""

    def exit_intersession(self):
        """Exit intersession"""

    def exit_intersession_to_tunnel(self):
        """Exit intersession"""

    def exit_intersession_to_cage(self):
        """Exit intersession"""

    def may_exit_intersession(self):
        """Exit intersession"""

    def may_exit_intersession_to_tunnel(self):
        """Exit intersession"""

    def may_exit_intersession_to_cage(self):
        """Exit intersession"""

    def is_cage(self):
        """Is cage"""

    def is_tunnel(self):
        """Is tunnel"""

    def is_intersession(self):
        """Is intersession"""
    # endregion

    transitions = transitions_allow_functions([
        dict(
            trigger=enter_tunnel,
            source=[SystemState.cage, SystemState.tunnel],
            dest=SystemState.tunnel,
            before=before_enter_tunnel,
            after=after_enter_tunnel,
        ),

        dict(
            trigger=exit_tunnel,
            source=SystemState.tunnel,
            dest=SystemState.cage,
            after=after_exit_tunnel,
        ),

        dict(
            trigger=enter_intersession,
            source=(SystemState.cage, SystemState.tunnel),
            dest=SystemState.intersession,
            after=after_enter_intersession,
        ),

        dict(
            trigger=reenter_intersession,
            source=SystemState.intersession,
            dest=SystemState.intersession,
            after=after_enter_intersession,
        ),

        dict(  # previous behavior
            trigger=exit_intersession,
            source=SystemState.intersession,
            dest=SystemState.intersession,
            after=after_exit_intersession,
        ),

        dict(
            trigger=exit_intersession_to_tunnel,
            source=SystemState.intersession,
            dest=SystemState.tunnel,
            after=after_exit_intersession_to_tunnel,
        ),
        dict(
            trigger=exit_intersession_to_cage,
            source=SystemState.intersession, dest=SystemState.cage,
            after=after_exit_intersession_to_cage,
        )
    ])
