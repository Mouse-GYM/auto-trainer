import math
import time
from datetime import datetime
from functools import partial
from itertools import chain
from pathlib import Path
from typing import Optional

from transitions import Machine

from autotrainer.core import (ProjectInfo, EventManager, SensorAnalysis, LoadCellMonitor, Offset3DTuple,
                              HeadbarPressureMonitor, transitions_allow_functions, SystemMessageHandler)
from autotrainer.core import ApiEventKind as BehaviorEventKind
from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.pose_elements import SceneElement, AllHandsParts
from autotrainer.core.multiproc import make_daemon_timer, no_op_timer
from autotrainer.core.video_detection import PresenceDetectionAttrs

from autotrainer.inference import PoseResponse, InferenceStatus
from autotrainer.inference.analysis import IntersessionResponse
from . import CaptureAnalysisResult

from .behavior_algorithm import BehaviorAlgorithm, BehaviorAlgoProps
from .inference_protocol import InferenceProtocol
from .intersession import IntersessionMachine, IntersessionState
from .pellet import PelletMachine, PelletState
from .pellet_device_protocol import PelletDeviceProtocol
from .state_machine import StateMachine
from .system_machine_state import SystemState
from .tunnel_device_protocol import TunnelDeviceProtocol

logger = get_verbose_logger(__name__)

# NB: this is to ensure we can patch the exact desired one (and only that one) from tests:
_clean_raw_data_timer = make_daemon_timer
_auto_clamp_release_timer = make_daemon_timer
_consider_end_session_timer = make_daemon_timer
_check_missing_timer = make_daemon_timer
_consider_disengage_autoclamp_timer = make_daemon_timer


#


class SystemMachine(StateMachine):

    states = [e for e in SystemState]

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

        self._project_info = project_info

        self._timer_consider_end_session = no_op_timer

        self._delay_timer_consider_end_session: Optional[float] = 2.0
        # delay to wait, when/once a pellet load is executed (on start),
        # and that a session is active, to trigger an eventual end_session()

        self._timer_consider_close_gate = no_op_timer
        self._timer_auto_clamp_disengage = no_op_timer
        self._disengage_auto_clamp_load_count = 0

        self._last_close_tunnel_gate_perf_t = -math.inf
        self._is_handling_diamond_triangle = False

        algo = self._algorithm = BehaviorAlgorithm(
            topcam_presence=topcam_presence,
        ) if algorithm is None else algorithm
        algo.project = project_info
        algo.session_starting += self._session_starting
        algo.session_ending += self._session_ended
        algo.property_changed += self._algorithm_property_changed
        algo.relay_transitions(self)
        # NB: could use the shift_xyz_handler.property_changed callback handler with LAST_PROCESSED_SHIFT_XYZ name too:
        algo.shift_xyz_handler.set_handle_processed_shift_xyz(self._handle_processed_shift_xyz)

        self._tunnel_device = tunnel_device
        self._msg_handler = msg_handler

        self._analysis = analysis
        if analysis is not None:
            analysis.load_cell_monitor.property_changed += self._load_cell_monitor_property_changed
            analysis.headbar_pressure_monitor.property_changed += self._headbar_pressure_monitor_property_changed
            analysis.load_cell_tare_monitor.tare_callback = self._load_cell_tare_requested

        self._inference = inference
        if inference is not None:
            inference.pose_response_ready += self._pose_changed
            inference.detection_result_ready += self._handle_detection_result
            inference.property_changed += self._handle_inference_property_changed

        self._pellet_device = pellet_device

        pellet_machine = self._pellet_machine = PelletMachine(self.algorithm, msg_handler, pellet_device)
        pellet_machine.events.pellet_loading += self._pellet_loading
        # pellet_machine.events.pellet_sending += self._pellet_sending
        # NB: _pellet_sending was used to trigger a start session, if one is not already running/recording,
        # *always*, by design, atm.
        # But this is already handled by load_cell_engaged property, basically.
        pellet_machine.events.state_changed += self._pellet_state_changed

        intersession_machine = self._intersession = IntersessionMachine(algo, self._project_info, inference)
        intersession_machine.events.on_analysis_ended += self._intersession_ended
        intersession_machine.events.state_changed += self._intersession_state_changed
        algo.relay_transitions(intersession_machine)


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
        EventManager.default().project = self._project_info
        self._algorithm.project = self._project_info
        self._intersession.project = self._project_info

    def before_enter_tunnel(self, *, reason: str = "NA"):
        EventManager.default().post_event_content(BehaviorEventKind.tunnelEnter)
        pellet_state = self._pellet_machine.state
        logger.debug("before_enter_tunnel: pellet_state=%s", pellet_state)
        algo = self._algorithm
        if algo.start_session(reason=f"{reason}->before_enter_tunnel"):
            self._update_magnet_position(algo.baseline_intensity)

    def after_enter_tunnel(self, *, reason: str = "NA"):
        if self._analysis is not None:
            self._evaluate_auto_clamp(self._analysis.headbar_pressure_monitor.is_engaged)

    def before_exit_tunnel(self, *, reason: str = "NA"):
        self._algorithm.system_state = SystemState.cage

    def after_exit_tunnel(self, *, reason: str = "NA"):
        self._update_magnet_position(self.algorithm.baseline_intensity)
        EventManager.default().post_event_content(BehaviorEventKind.tunnelExit)
        if self._algorithm.is_in_session:
            self._algorithm.end_session(reason=f"{reason}->after_exit_tunnel")

    def before_enter_intersession(self):
        # current system_state should be tunnel here
        self._algorithm.system_state = SystemState.intersession

    def after_enter_intersession(self):
        project = self._project_info.to_local_value()
        self._intersession.perform_segmentation()
        algo = self._algorithm
        auto_close_gate_cfg = algo.auto_close_gate_on_intersession_config
        if auto_close_gate_cfg.enabled:
            duration = datetime.now() - project.when  # could/should be todo: have session duration recorded in project-session info.
            if auto_close_gate_cfg.session_min_duration <= duration.total_seconds():
                timer = self._timer_consider_close_gate = make_daemon_timer(0.1, self._consider_close_gate_during_intersession)
                timer.start()
            else:
                logger.verbose("Not starting timer to auto-close gate when mouse in cage confirmed ; session duration=%s",
                           duration)

    def before_exit_intersession_to_cage(self):
        self._algorithm.system_state = SystemState.cage
        self._pellet_machine.environment_changed(caller="before_exit_intersession_to_cage")

    def before_exit_intersession_to_tunnel(self):
        self.state = SystemState.tunnel
        # set/force tunnel state required now, otherwise enter_tunnel is refused here after,
        # another possibility would be to have a dedicated trigger like "re_enter_tunnel_from_end_of_intersession"
        self._algorithm.system_state = SystemState.tunnel
        self.enter_tunnel(reason="exit_intersession_to_tunnel")
        # # EDIT: even not sure it's needed anymore ? at least not for current tests. trying without..
        if not self._algorithm.is_in_session:
            # only needed if not start a new session,
            # given when a new session is started, the pellet machine already receives a session_starting event/callback
            # which already makes the necessary move(s).
            self._pellet_machine.environment_changed(caller="before_exit_intersession_to_tunnel")

    @staticmethod
    def _clean_raw_data(project: ProjectInfo, *, wait_before_clean: float = 10):
        # NB: convert to local value immediately,
        # so that if the shared values are modified in between the timer triggers,
        # then the good values are still used
        project = project.to_local_value()

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

    @BehaviorAlgorithm.relay_func
    def _session_starting(self):
        pass

    @BehaviorAlgorithm.relay_func
    def _session_ended(self):
        # 5/16/25 should not remove auto-clamp at session end for current testing.
        # TODO: make this configurable.
        # if self._tunnel_device is not None:
        #    self._update_magnet_position(self.algorithm.baseline_intensity)
        project = self.project
        algo = self.algorithm
        logger.verbose(
            "session ended: intersession.state=%s system_machine.state=%s algo.system_state=%s "
            "pellet_machine.state=%s intersession_enabled=%s session_mouse_seen=%s",
            # " segment_config=%s detection_config=%s",
            self._intersession.state, self.state, algo.system_state,
            self._pellet_machine.state,
            algo.intersession_enabled, algo.session_mouse_seen,
            # self._intersession._segmentation_configuration,
            # self._intersession._detection_configuration,
        )
        #
        can_perform_analysis = (
            algo.can_perform_intersession_analysis()
            and self._intersession.can_perform_segmentation()
        )
        # first:
        if not algo.session_mouse_seen and project is not None:
            # assert not can_perform_analysis  # could have
            if algo.clean_raw_data_on_inactive_session:
                self._clean_raw_data(project)
        #
        if can_perform_analysis and self.state in {
            SystemState.tunnel,
            SystemState.cage,
        }:
            self.enter_intersession()
        else:
            inference = self._inference
            if inference is not None:
                if self._intersession.state != IntersessionState.idle:
                    logger.warning(
                        "intersession state not idle: %s in progress, not setting inference back to online. "
                        "segment_config=%s detection_config=%s",
                        self._intersession.state,
                        self._intersession._segmentation_configuration,
                        self._intersession._detection_configuration,
                    )
                else:
                    inference.set_inference_to_online()
            #
            algo.session_processing_ending(CaptureAnalysisResult.CAPTURE_ONLY)

    @BehaviorAlgorithm.relay_func
    def _intersession_ended(self):
        if self.state == SystemState.intersession:
            self._timer_consider_close_gate.cancel()
            self._tunnel_device.open_tunnel_gate()  # always ensure open gate on intersession ended
            logger.debug("_intersession_ended: load_cell.engaged=%s",
                         self._analysis.load_cell_monitor.is_engaged)
            if self._analysis.load_cell_monitor.is_engaged and not self._algorithm.algo_paused:
                self.exit_intersession_to_tunnel()
            else:
                self.exit_intersession_to_cage()

    @BehaviorAlgorithm.relay_func(wait=False)
    def _handle_inference_property_changed(self, name: str, new_value, prev_value):
        if name == InferenceProtocol.STATUS:
            logger.verbose("Inference status change: %s -> %s ; system_state=%s",
                           prev_value, new_value, self.state)
            if new_value not in {InferenceStatus.live, InferenceStatus.intersession}:
                self._timer_consider_end_session.cancel()
            if (
                new_value == InferenceStatus.live
                and self.state == SystemState.cage
            ):
                if self._analysis.load_cell_monitor.is_engaged and not self._algorithm.algo_paused:
                    self.enter_tunnel(reason="inference_begin_live_when_load_cell_engaged")
                # this is only used at app starts, so unregister:
                # self._inference.property_changed -= self._handle_inference_property_changed
                # NO: in case of stop->start acquisition of/inside main app we still need it.

    @BehaviorAlgorithm.relay_func(wait=False)
    def _headbar_pressure_monitor_property_changed(self, name: str, value, _):
        if self.state == SystemState.intersession:
            # TODO new need event kind
            # EventManager.default().post_event(BehaviorEventKind.headfixLoadCellChangedInIntersession, context=value)
            return

        if name == HeadbarPressureMonitor.IS_ENGAGED_PROPERTY:
            EventManager.default().post_event_content(BehaviorEventKind.headFixationForceDetectorChanged, context=value)
            self._evaluate_auto_clamp(value)

    @BehaviorAlgorithm.relay_func(wait=False)
    def _load_cell_monitor_property_changed(self, name: str, value, _):
        if self.state == SystemState.intersession:
            EventManager.default().post_event_content(BehaviorEventKind.headfixLoadCellChangedInIntersession,
                                                      context=value)
            return

        if name == LoadCellMonitor.IS_ENGAGED_PROPERTY:
            algo = self._algorithm
            EventManager.default().post_event_content(BehaviorEventKind.headfixLoadCellChanged, context=value)
            if value:
                self._analysis.global_animal_presence_monitor.stop()
                algo.presence_missing = False
                if self.state == SystemState.cage:
                    # when app start inference is slow and takes several 10s to become live,
                    # so we have to check it:
                    if self._inference.status == InferenceStatus.live and not algo.algo_paused:
                        self.enter_tunnel(reason="load_cell_engaged_when_in_cage")
                    # see _handle_inference_property_changed
                else:
                    EventManager.default().post_event_content(BehaviorEventKind.headfixLoadCellChangedWrongState,
                                                              context=self.state)
            else:
                if self._inference.status == InferenceStatus.live:
                    self._analysis.global_animal_presence_monitor.start()
                if self.state == SystemState.tunnel and self.intersession.state == IntersessionState.idle:
                    logger.info("%s False, exiting tunnel ..", LoadCellMonitor.IS_ENGAGED_PROPERTY)
                    self.exit_tunnel(reason="load_cell_disengaged_when_tunnel")
                else:
                    EventManager.default().post_event_content(BehaviorEventKind.headfixLoadCellChangedWrongState,
                                                              context=self.state)

    @BehaviorAlgorithm.relay_func
    def _evaluate_auto_clamp(self, is_headbar_pressure_engaged: bool):
        algo = self._algorithm
        if not algo.head_fixation_enabled:
            logger.info("auto-clamp disabled (no action taken)")
            return
        logger.verbose("headbar pressure engaged: %s", is_headbar_pressure_engaged)
        if not is_headbar_pressure_engaged:
            logger.info("auto-clamp detector not engaged (no action taken)")
            return
        logger.debug("system state: %s", self.state)
        if self.state == SystemState.tunnel:
            algo = self._algorithm
            logger.info("auto-clamp setting position to %s", algo.auto_clamp_intensity)
            self._update_magnet_position(algo.auto_clamp_intensity)
            self._disengage_auto_clamp_load_count = 0
            self._timer_auto_clamp_disengage.cancel()
            t_delay = algo.auto_clamp_no_activity_release_delay
            if t_delay >= 0:
                logger.debug("starting new timer for disengage_auto_clamp in %.2f seconds", t_delay)
                new_timer = self._timer_auto_clamp_disengage = _consider_disengage_autoclamp_timer(
                    t_delay, self._disengage_auto_clamp,
                )
                new_timer.start()
            EventManager.default().post_event_content(BehaviorEventKind.headFixationEnabled)
        else:
            logger.debug("auto-clamp position not sent (not in tunnel)")

    @BehaviorAlgorithm.relay_func
    def _load_cell_tare_requested(self):
        if not self._analysis.load_cell_monitor.is_engaged:
            self._tunnel_device.tare_load_cell()
            EventManager.default().post_event_content(BehaviorEventKind.headfixAutoTare)
        return False

    # @BehaviorAlgorithm.relay_func(wait=False)
    # not needed, already called by _pose_changed which has already it.
    def _handle_diamond_triangle_offset_changed(self, offset: Optional[Offset3DTuple]):
        if offset is None:
            return
        if (
            self._state == SystemState.tunnel
            and self._pellet_machine.state == PelletState.monitoring
            # TODO: monitoring only happens when mouse hands near pellet seen, which uncover the pellet,
            #  we might want to also handle/capture it when state is send and covering ?
            #  It might be that it's not enough though.. we want be sure the last command is/was send_pellet,
            #   even if there was some manual move after that.
            #  And we could also decide to check in SystemState.cage as well (as far as last command is send_pellet) ?
            and self._pellet_machine.can_use_pellet_command()
        ):
            last_pos = self._pellet_device.last_position
            if last_pos is not None:
                if not self._is_handling_diamond_triangle:
                    self._is_handling_diamond_triangle = True
                    logger.info("Starting handling diamond-triangle offset ; current offset=%s pos=%s",
                                offset.humanize(), last_pos.humanize())
                self._algorithm.handle_diamond_triangle_offset(offset, last_pos)
        else:
            if self._is_handling_diamond_triangle:
                self._is_handling_diamond_triangle = False
                measured_drift = self._algorithm.diamond_triangle_drift
                logger.info("Stopped handling diamond-triangle offset ; measured drift = %s",
                            None if measured_drift is None else measured_drift.humanize())

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
        check_cover_distance = not algo.is_in_session and (
                (pellet_machine.state == PelletState.monitoring and algo.pellet_cover_enabled)
                or (pellet_machine.state == PelletState.covering)
        )
        if check_cover_distance:
            algo.handle_cover_pellet_offset(offset)
            # never consider the check release position when we checked the cover one
            return
        # otherwise, given can_use_pellet_command() is True (check above),
        # we know we have to check release pos distance if state is monitoring:
        check_release_distance = (pellet_machine.state == PelletState.monitoring)
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
        prev_hands_seen_near_pellet = algo.hands_near_pellet_seen
        algo.pellet_hands_min_distance = min_dist
        if __debug__:
            prev_dist = getattr(self, "_prev_pellet_hands_dist", math.inf)
            if f"{prev_dist:.0f}" != f"{prev_dist:.0f}":
                logger.spam("pellet_hands min distance: %.3f -> %.3f", prev_dist, min_dist)
            self._prev_pellet_hands_dist = min_dist
        #
        if algo.hands_near_pellet_seen and not prev_hands_seen_near_pellet:
            self._pellet_machine.environment_changed(caller="hands_seen_near_pellet")

    @BehaviorAlgorithm.relay_func(wait=False)
    def _pose_changed(self, response: PoseResponse):
        self._handle_diamond_triangle_offset_changed(
            response.get_parts_3d_offset(SceneElement.Diamond, SceneElement.Triangle))

        self._handle_star_triangle_offset_changed(
            response.get_parts_3d_offset(SceneElement.Star, SceneElement.Triangle))

        self._handle_triangle_pellet_offset_changed(
            response.get_parts_3d_offset(SceneElement.Triangle, SceneElement.Pellet))
        #
        algo = self._algorithm
        if algo.is_in_session and not algo.session_mouse_seen and response.mouse_seen:
            logger.verbose("session first mouse_seen: parts=%s locations=%s", response.parts_flags, response.locations)
        #
        algo.pellet_seen(response.pellet_seen)
        algo.mouse_seen(response.mouse_seen)
        algo.triangle_seen(response.triangle_seen)
        if not algo.pellet_delivery_enabled:
            return
        #
        self._handle_pellet_hands_offsets(response)
        #
        self._pellet_machine.pellet_seen(response.pellet_seen)

    @BehaviorAlgorithm.relay_func
    def _disengage_auto_clamp(self):
        logger.info("disengaging auto-clamp ..")
        pellet_dev = self._pellet_device
        algo = self._algorithm
        if algo.is_in_session:
            logger.debug("sending tone to indicate auto-clamp disabled (tunnel=%s)", self._tunnel_device)
            pellet_dev.play_tone(self.algorithm.auto_clamp_release_tone_freq, 0.5)
        if self._tunnel_device is not None:  # condition seems not necessary... but some test assert it
            logger.debug(
                "changing magnet to baseline intensity in %.2f seconds", algo.auto_clamp_release_tone_delay)
            timer = self._timer_auto_clamp_disengage = _auto_clamp_release_timer(
                algo.auto_clamp_release_tone_delay,
                partial(self._update_magnet_position, algo.baseline_intensity),
            )
            timer.start()

    @BehaviorAlgorithm.relay_func(wait=False)
    def _consider_close_gate_during_intersession(self):
        algo = self._algorithm
        if algo.algo_paused:
            # algo has been paused, so cancel totally.
            return
        if self._state != SystemState.intersession:
            # only valid for intersession
            logger.debug("not anymore intersession, skipping auto-close-gate")
            return
        load_cell_mon = self._analysis.load_cell_monitor.context
        topcam_pres = algo.top_camera_presence_detection
        auto_close_gate_cfg = algo.auto_close_gate_on_intersession_config
        perf_now = time.perf_counter()
        if (
            not load_cell_mon.is_engaged
            and topcam_pres.last_presence_start_perf_c >= load_cell_mon.last_disengaged_perf_c
            # ensure load-cell is not re-entered by the mouse:
            and topcam_pres.last_presence_start_perf_c > load_cell_mon.last_engaged_perf_c
            and perf_now - topcam_pres.last_presence_start_perf_c > auto_close_gate_cfg.delay_after_cage_enter
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
                max(0.01,
                    auto_close_gate_cfg.delay_after_cage_enter - (perf_now - topcam_pres.last_presence_start_perf_c))
            )
            timer = self._timer_consider_close_gate = make_daemon_timer(delay, self._consider_close_gate_during_intersession)
            timer.start()

    @BehaviorAlgorithm.relay_func(wait=False)
    def _algorithm_property_changed(self, name: str, new_value, _):
        # Always back off to the baseline intensity when auto-clamp is disabled.
        pellet_dev = self._pellet_device
        #
        if name == BehaviorAlgoProps.HEAD_FIXATION_ENABLED:
            if not new_value:
                logger.debug("auto-clamp disabled (backing off to baseline intensity)")
                self._disengage_auto_clamp()

        elif name == BehaviorAlgoProps.AUTO_CORRECT_MOTOR_DRIFT:
            pellet_dev.set_auto_correct_motor_drift(new_value)

        elif name == BehaviorAlgoProps.HANDS_NEAR_PELLET_SEEN:
            self._pellet_machine.environment_changed(must_release=new_value)

        elif name == BehaviorAlgoProps.ALGO_PAUSED:
            algo = self._algorithm
            tunnel_dev = self._tunnel_device
            self._timer_consider_end_session.cancel()
            self._timer_auto_clamp_disengage.cancel()
            self._timer_consider_close_gate.cancel()
            if new_value:
                if algo.is_in_session:
                    if algo.intersession_state == IntersessionState.idle:
                        algo.end_session(reason="algo_paused")
                tunnel_dev.open_tunnel_gate()
                tunnel_dev.update_head_magnet_intensity(0)
                if self._pellet_machine.state != PelletState.retract:
                    pellet_dev.send_pellet()  # better done.. so to be on correct position
                    #  for following send_retract (which is a relative move):
                    pellet_dev.send_retract()
                if algo.pellet_cover_enabled:
                    pellet_dev.cover_pellet()
            else:
                tunnel_dev.open_tunnel_gate()
                tunnel_dev.update_head_magnet_intensity(algo.baseline_intensity)
                pellet_dev.send_pellet()
                #
                # trigger load cell property changed check, so that new session will be started if mouse still in tunnel
                self._load_cell_monitor_property_changed(
                    LoadCellMonitor.IS_ENGAGED_PROPERTY, self._analysis.load_cell_monitor.is_engaged, None
                )
                # also trigger others checks:
                self._handle_inference_property_changed(InferenceProtocol.STATUS, self._inference.status, None)

    def _update_magnet_position(self, position: int):
        if self._tunnel_device is not None:
            self._tunnel_device.update_head_magnet_intensity(position)

    @BehaviorAlgorithm.relay_func
    def _pellet_loading(self):
        self._timer_auto_clamp_disengage.cancel()
        self._disengage_auto_clamp_load_count += 1
        algo = self._algorithm
        if self._disengage_auto_clamp_load_count >= algo.auto_clamp_release_load_count:
            self._disengage_auto_clamp()
        if algo.is_in_session:
            prev_timer = self._timer_consider_end_session
            if not prev_timer.finished.is_set():
                logger.debug("cancelling unfinished previous timer: %s", prev_timer)
            prev_timer.cancel()
            self._timer_consider_end_session = _consider_end_session_timer(
                self._delay_timer_consider_end_session,
                partial(self._consider_end_session, reason="pellet_loading"))
            self._timer_consider_end_session.start()

    def _pellet_state_changed(self, old_value, new_value):
        logger.info("pellet_state_changed: %s -> %s", old_value, new_value)

    def _intersession_state_changed(self, old_value, new_value):
        self._algorithm.intersession_state = new_value

    @BehaviorAlgorithm.relay_func(wait=False)
    # called by a timer, so can use wait=False (to not always recreate event for the wait sync)
    def _consider_end_session(self, *, reason: str = "NA"):
        # Do not end if the mouse is still in the tunnel and a pellet is seen or the pellet deliver is in the sending
        # or releasing states. Otherwise, there will be no trigger to start a new session and recording (tunnel entry
        # or sending the pellet)
        if (not self._algorithm.is_in_session
            or (self.state == SystemState.tunnel
                and self._pellet_machine.state in {
                    PelletState.sending, PelletState.releasing, PelletState.monitoring,
                    # PelletState.loading,
                }
            )
        ):
            logger.debug("_consider_end_session[%s]: not ending: is_in_session=%s state=%s pellet=%s",
                         reason, self._algorithm.is_in_session, self.state, self._pellet_machine.state)
            return

        if self.algorithm.end_session(reason=f"{reason}->consider_end_session"):
            # force analysis to False,
            # this will trigger a new start session if mouse still there
            self._analysis.load_cell_monitor.is_engaged = False

    @BehaviorAlgorithm.relay_func(wait=False)
    def _handle_detection_result(self, res: IntersessionResponse):
        algo = self._algorithm
        if res.food_consumed > 0:
            algo.increase_pellets_consumed(res.food_consumed)
        if res.successful_reaches > 0:
            algo.increase_successful_reaches(res.successful_reaches)
        if res.pellets_presented > 0:
            algo.increase_pellets_presented(res.pellets_presented)
        #
        shift_xyz = Offset3DTuple(res.pellet_x, res.pellet_y, res.pellet_z)
        algo.shift_xyz_handler.put_new_shift_xyz(shift_xyz)

    def _handle_processed_shift_xyz(self, shift_xyz: Offset3DTuple):
        logger.verbose("Received processed shift xyz: %s", shift_xyz)
        dev = self._pellet_device
        if dev is not None and self.algorithm.intersession_pellet_shift_enabled:
            for val, meth, kind in ((shift_xyz[0], dev.set_x, BehaviorEventKind.intersessionShiftX),
                                    (shift_xyz[1], dev.set_y, BehaviorEventKind.intersessionShiftY),
                                    (shift_xyz[2], dev.set_z, BehaviorEventKind.intersessionShiftZ)):
                if val != 0:
                    meth(val, absolute=False)
                    EventManager.default().post_event_content(kind, context=val)
                else:
                    logger.debug("%s == 0 ; skip", kind)

    # region State Machine Requirements
    # Methods required for model_override=True to work.
    def trigger(self):
        pass

    def may_trigger(self):
        pass

    def enter_tunnel(self, *, reason: str = "NA"):
        pass

    def may_enter_tunnel(self):
        pass

    def exit_tunnel(self, *, reason: str = "NA"):
        pass

    def may_exit_tunnel(self):
        pass

    def enter_intersession(self):
        pass

    def may_enter_intersession(self):
        pass

    def exit_intersession(self):
        pass

    def exit_intersession_to_tunnel(self):
        pass

    def exit_intersession_to_cage(self):
        pass

    def may_exit_intersession(self):
        pass

    def may_exit_intersession_to_tunnel(self):
        pass

    def may_exit_intersession_to_cage(self):
        pass

    def is_cage(self):
        pass

    def is_tunnel(self):
        pass

    def is_intersession(self):
        pass
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
            before=before_exit_tunnel,
            after=after_exit_tunnel,
        ),

        dict(
            trigger=enter_intersession,
            source=(SystemState.cage, SystemState.tunnel),
            dest=SystemState.intersession,
            before=before_enter_intersession,
            after=after_enter_intersession,
        ),

        dict(  # previous behavior
            trigger=exit_intersession,
            source=SystemState.intersession, dest=SystemState.cage,
            before=before_exit_intersession_to_cage,
        ),

        dict(
            trigger=exit_intersession_to_tunnel,
            source=SystemState.intersession, dest=SystemState.tunnel,
            before=before_exit_intersession_to_tunnel,
        ),
        dict(
            trigger=exit_intersession_to_cage,
            source=SystemState.intersession, dest=SystemState.cage,
            before=before_exit_intersession_to_cage,
        )
    ])
