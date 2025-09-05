import math
import time
from functools import partial
from itertools import chain
from pathlib import Path
from typing import Optional, List, Tuple

from transitions import Machine

from autotrainer.core import (ProjectInfo, EventManager, MessageHandler, SensorAnalysis, LoadCellMonitor,
                              HeadbarPressureMonitor, Motor)
from autotrainer.core import Offset3DTuple
from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.pose_elements import SceneElement, AllHandsParts
from autotrainer.core.multiproc import DaemonTimer

from autotrainer.inference import PoseResponse, InferenceStatus

from .analysis.intersession_process import IntersessionResponse
from .behavior_algorithm import BehaviorAlgorithm, BehaviorAlgoProps
from .behavior_event_kind import BehaviorEventKind
from .inference_protocol import InferenceProtocol
from .intersession import IntersessionMachine, IntersessionState
from .pellet import PelletMachine, PelletState
from .pellet_device_protocol import PelletDeviceProtocol
from .state_machine import StateMachine
from .system_machine_state import SystemState
from .tunnel_device_protocol import TunnelDeviceProtocol

logger = get_verbose_logger(__name__)


# NB: this is to ensure we can patch the exact desired one (and only that one) from tests:
_clean_raw_data_timer = DaemonTimer
_auto_clamp_release_timer = DaemonTimer
_consider_end_session_timer = DaemonTimer
_check_missing_timer = DaemonTimer
_consider_disengage_autoclamp_timer = DaemonTimer

#


class SystemMachine(StateMachine):
    states = [e for e in SystemState]

    transitions = [
        {"trigger": "enter_tunnel", "source": [SystemState.cage, SystemState.tunnel], "dest": SystemState.tunnel,
         "before": "before_enter_tunnel", "after": "after_enter_tunnel"},

        {"trigger": "exit_tunnel", "source": SystemState.tunnel, "dest": SystemState.cage,
         "before": "before_exit_tunnel", "after": "after_exit_tunnel"},

        {"trigger": "enter_intersession", "source": (SystemState.cage, SystemState.tunnel), "dest": SystemState.intersession,
         "before": "before_enter_intersession", "after": "after_enter_intersession"},

        dict(  # previous behavior
            trigger="exit_intersession",
            source=SystemState.intersession, dest=SystemState.cage,
            before="before_exit_intersession_to_cage",
        ),

        dict(
            trigger="exit_intersession_to_tunnel",
            source=SystemState.intersession, dest=SystemState.tunnel,
            before="before_exit_intersession_to_tunnel",
        ),
        dict(
            trigger="exit_intersession_to_cage",
            source=SystemState.intersession, dest=SystemState.cage,
            before="before_exit_intersession_to_cage",
        )
    ]

    def __init__(self,
                 algorithm: Optional[BehaviorAlgorithm] = None,
                 project_info: Optional[ProjectInfo] = None,
                 msg_handler: MessageHandler = None,
                 analysis: SensorAnalysis = None,
                 tunnel_device: TunnelDeviceProtocol = None,
                 pellet_device: PelletDeviceProtocol = None,
                 inference: InferenceProtocol = None,
                 ):

        initial_state = SystemState.cage
        super().__init__(initial_state=initial_state)

        self.machine = Machine(
            model=[self], states=SystemMachine.states, transitions=SystemMachine.transitions,
            auto_transitions=False, initial=initial_state, model_override=True,
        )

        self._project_info = project_info

        no_op_timer = DaemonTimer(0, lambda: None)
        no_op_timer.start()

        self._timer_consider_end_session = no_op_timer
        self._delay_timer_consider_end_session: Optional[float] = 2.0

        self._timer_auto_clamp_disengage = no_op_timer
        self._disengage_auto_clamp_load_count = 0

        self._motor_axis_flips = Offset3DTuple(1, 1, 1)

        algorithm = self._algorithm = algorithm if algorithm is not None else BehaviorAlgorithm()
        algorithm.project = project_info
        algorithm.session_starting += self._session_starting
        algorithm.session_ending += self._session_ended
        algorithm.property_changed += self._algorithm_property_changed

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

        intersession_machine = self._intersession = IntersessionMachine(self.algorithm, self._project_info, inference)
        intersession_machine.events.on_analysis_ended += self._intersession_ended
        intersession_machine.events.state_changed += self._intersession_state_changed

        # need to set it directly, when we start all state are "OFF/0": no presence detected, etc..
        # so if that's stay as is then there need to be the timer already setup:
        self._timer_check_missing = _check_missing_timer(self._algorithm.presence_missing_delay,
                                                         self._check_presence_missing)
        self._timer_check_missing.start()

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

    def before_enter_tunnel(self, *, reason: str="NA"):
        EventManager.default().post_event_content(BehaviorEventKind.tunnelEnter)
        pellet_state = self._pellet_machine.state
        logger.debug("before_enter_tunnel: pellet_state=%s", pellet_state)
        # if pellet_state in {
        #     PelletState.sending,
        #     PelletState.covering,
        #     PelletState.prerelease,
        #     PelletState.releasing,
        #     PelletState.monitoring,
        #     PelletState.retract,
        # }:
        if True:
            algo = self._algorithm
            if algo.start_session(reason=f"{reason}->before_enter_tunnel"):
                algo.reset_session_pellet_count()
                self._update_magnet_position(self.algorithm.baseline_intensity)
                algo.system_state = SystemState.tunnel

    def after_enter_tunnel(self, *, reason: str="NA"):
        if self._analysis is not None:
            self._evaluate_auto_clamp(self._analysis.headbar_pressure_monitor.is_engaged)

    def before_exit_tunnel(self, *, reason: str="NA"):
        self._algorithm.system_state = SystemState.cage

    def after_exit_tunnel(self, *, reason: str="NA"):
        self._update_magnet_position(self.algorithm.baseline_intensity)
        EventManager.default().post_event_content(BehaviorEventKind.tunnelExit)
        self.algorithm.end_session(reason=f"{reason}->after_exit_tunnel")

    def before_enter_intersession(self):
        # current system_state should be tunnel here
        self._algorithm.system_state = SystemState.intersession

    def after_enter_intersession(self):
        self._intersession.perform_segmentation()

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
    def _clean_raw_data(project):
        # NB: get/read the current session index value immediately,
        # this ensures that if it's changed by main process/thread then we are cleaning the good/correct one !!
        session_value = project.session.value

        def do_clean():
            for cam_name in (project.camera_1, project.camera_2):
                paths = map(Path, chain(
                    project.get_video_path(cam_name, session=session_value, allow_overwrite=True),
                    [project.get_intersession_pose_path(cam_name, session=session_value, allow_overwrite=True,
                                                        suffix="_live")],
                ))
                for path in paths:
                    if path.exists():
                        logger.debug("removing %s", path)
                        path.unlink(missing_ok=True)
        # using timer given when called the monitor data queue might still be writing to disk/still be in live session,
        # making the deletes to not work here
        t = _clean_raw_data_timer(15, do_clean)
        # changed timer to 15s: seen some cases where close of file handles in monitor data queue was bit slower,
        # and made some of the data files not be removed (given written to after).
        # if that still happens (like with overloaded system), then some files will be left on disk still.
        t.start()

    def _session_starting(self):
        pellet_dev = self._pellet_device
        if pellet_dev is not None:
            self._motor_axis_flips = pellet_dev.get_motor_flips()
            logger.debug("read motor axis flips: %s", self._motor_axis_flips)

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
        can_perform_analysis = algo.can_perform_intersession_analysis()
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

    def _intersession_ended(self):
        if self.state == SystemState.intersession:
            logger.debug("_intersession_ended: load_cell.engaged=%s",
                         self._analysis.load_cell_monitor.is_engaged)
            if self._analysis.load_cell_monitor.is_engaged:
                self.exit_intersession_to_tunnel()
            else:
                self.exit_intersession_to_cage()

    def _handle_inference_property_changed(self, name: str, new_value, prev_value):
        if name == InferenceProtocol.STATUS:
            logger.verbose("Inference status change: %s -> %s ; system_state=%s",
                           prev_value, new_value, self.state)
            if new_value in {InferenceStatus.live, InferenceStatus.intersession}:
                self._timer_check_missing = _check_missing_timer(0.5, self._check_presence_missing)
                self._timer_check_missing.start()
            else:
                self._timer_check_missing.cancel()
                self._timer_consider_end_session.cancel()
            if (
                new_value == InferenceStatus.live
                and self.state == SystemState.cage
            ):
                if self._analysis.load_cell_monitor.is_engaged:
                    self.enter_tunnel(reason="inference_begin_live_when_load_cell_engaged")
                # this is only used at app starts, so unregister:
                # self._inference.property_changed -= self._handle_inference_property_changed
                # NO: in case of stop->start acquisition of/inside main app we still need it.

    def _headbar_pressure_monitor_property_changed(self, name: str, value, _):
        if self.state == SystemState.intersession:
            # TODO new need event kind
            # EventManager.default().post_event(BehaviorEventKind.headfixLoadCellChangedInIntersession, context=value)
            return

        if name == HeadbarPressureMonitor.IS_ENGAGED_PROPERTY:
            EventManager.default().post_event_content(BehaviorEventKind.headFixationForceDetectorChanged, context=value)
            self._evaluate_auto_clamp(value)

    def _load_cell_monitor_property_changed(self, name: str, value, _):
        if self.state == SystemState.intersession:
            EventManager.default().post_event_content(BehaviorEventKind.headfixLoadCellChangedInIntersession,
                                                      context=value)
            return

        if name == LoadCellMonitor.IS_ENGAGED_PROPERTY:
            EventManager.default().post_event_content(BehaviorEventKind.headfixLoadCellChanged, context=value)
            cur_timer_check_missing = self._timer_check_missing
            cur_timer_check_missing.cancel()
            if value:
                self._algorithm.presence_missing = False
                if self.state == SystemState.cage:
                    # when app start inference is slow and takes several 10s to become live,
                    # so we have to check it:
                    if self._inference.status == InferenceStatus.live:
                        self.enter_tunnel(reason="load_cell_engaged_when_in_cage")
                    # see _handle_inference_property_changed
                else:
                    EventManager.default().post_event_content(BehaviorEventKind.headfixLoadCellChangedWrongState,
                                                              context=self.state)
            else:
                cur_timer_check_missing = _check_missing_timer(self._algorithm.presence_missing_delay,
                                                               self._check_presence_missing)
                cur_timer_check_missing.start()
                if self.state == SystemState.tunnel and self.intersession.state == IntersessionState.idle:
                    logger.info("%s False, exiting tunnel ..", LoadCellMonitor.IS_ENGAGED_PROPERTY)
                    self.exit_tunnel(reason="load_cell_disengaged_when_tunnel")
                else:
                    EventManager.default().post_event_content(BehaviorEventKind.headfixLoadCellChangedWrongState,
                                                              context=self.state)

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
            if True or self._tunnel_device is not None:  # condition seems not necessary
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

    def _load_cell_tare_requested(self):
        if self.state != SystemState.tunnel:
            self._tunnel_device.tare_load_cell()
            EventManager.default().post_event_content(BehaviorEventKind.headfixAutoTare)
        return False

    def _handle_diamond_triangle_offset_changed(self, offset: Optional[Offset3DTuple]):
        if (
            offset is not None
            and self._state == SystemState.tunnel
            and self._pellet_machine.state == PelletState.monitoring
            and self._pellet_machine.can_use_pellet_command()
        ):
            last_position = self._pellet_device.last_position
            if last_position is not None and offset is not None:
                self._algorithm.handle_diamond_triangle_offset(
                    offset, last_position, flips=self._motor_axis_flips)

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
        for part in AllHandsParts:
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

    def _pose_changed(self, response: PoseResponse):
        self._handle_diamond_triangle_offset_changed(
            response.get_parts_3d_offset(SceneElement.Diamond, SceneElement.Triangle))

        self._handle_star_triangle_offset_changed(
            response.get_parts_3d_offset(SceneElement.Star, SceneElement.Triangle))

        # if response.pellet_seen:  # not necessary, already handled by response.get_parts_3d_offset
        self._handle_triangle_pellet_offset_changed(
            response.get_parts_3d_offset(SceneElement.Triangle, SceneElement.Pellet))
        #
        algo = self._algorithm
        algo.pellet_seen(response.pellet_seen)
        algo.mouse_seen(response.mouse_seen)
        algo.triangle_seen(response.triangle_seen)
        if not algo.pellet_delivery_enabled:
            return
        #
        self._handle_pellet_hands_offsets(response)
        #
        self._pellet_machine.pellet_seen(response.pellet_seen)

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
            timer = _auto_clamp_release_timer(
                algo.auto_clamp_release_tone_delay,
                partial(self._update_magnet_position, algo.baseline_intensity),
            )
            timer.start()

    def _algorithm_property_changed(self, name: str, new_value, _):
        # Always back off to the baseline intensity when auto-clamp is disabled.
        pellet_dev = self._pellet_device
        if name == BehaviorAlgoProps.HEAD_FIXATION_ENABLED:
            if not new_value:
                logger.debug("auto-clamp disabled (backing off to baseline intensity)")
                self._disengage_auto_clamp()
        elif name == BehaviorAlgoProps.PELLET_MOTOR_DRIFT:
            if new_value is not None and self._algorithm.auto_correct_motors_drift:
                pellet_dev.set_motors_drift(new_value)

        elif name == BehaviorAlgoProps.AUTO_CORRECT_MOTOR_DRIFT:
            pellet_dev.set_auto_correct_motor_drift(new_value)
            # unnecessary:
            # ensure the current deliver position is corrected (no more drift applied):
            # if not new_value:
            #     pellet_dev.set_motors_drift(Offset3DTuple(0, 0, 0))
                # # for set_coord in (pellet_dev.set_x, pellet_dev.set_y, pellet_dev.set_z):
                # #     set_coord(0, absolute=False)
                # given set_motors_drift already does it.

    def _update_magnet_position(self, position: int):
        if self._tunnel_device is not None:
            self._tunnel_device.update_head_magnet_intensity(position)

    def _pellet_loading(self):
        self._timer_auto_clamp_disengage.cancel()
        self._disengage_auto_clamp_load_count += 1
        algo = self._algorithm
        if self._disengage_auto_clamp_load_count >= algo.auto_clamp_release_load_count:
            self._disengage_auto_clamp()
        if algo.is_in_session:
            prev_timer = self._timer_consider_end_session
            if prev_timer.finished.is_set():
                self._timer_consider_end_session = _consider_end_session_timer(
                    self._delay_timer_consider_end_session,
                    partial(self._consider_end_session, reason="pellet_loading"))
                self._timer_consider_end_session.start()
            else:
                logger.verbose("%s: prev timer not finished for pellet loading ; prev_timer=%s",
                               self, prev_timer)

    def _pellet_sending(self):
        # nb: not used anymore
        if self.state == SystemState.tunnel and not self._algorithm.is_in_session:
            self._algorithm.start_session(reason="pellet_sending")

    def _pellet_state_changed(self, old_value, new_value):
        logger.info("pellet_state_changed: %s -> %s", old_value, new_value)

    def _intersession_state_changed(self, old_value, new_value):
        self._algorithm.intersession_state = new_value

    def _consider_end_session(self, *, reason: str="NA"):
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
            return

        if self.algorithm.end_session(reason=f"{reason}->consider_end_session"):
            # force analysis to False,
            # this will trigger a new start session if mouse still there
            self._analysis.load_cell_monitor.is_engaged = False

    def _handle_detection_result(self, res: IntersessionResponse):
        algo = self._algorithm
        if res.food_consumed > 0:
            algo.day_pellet_count += res.food_consumed
            algo.session_pellet_count += res.food_consumed
        if res.successful_reaches > 0:
            algo.successful_reaches = res.successful_reaches
        if res.pellets_presented > 0:
            algo.pellets_presented = res.pellets_presented
        dev = self._pellet_device
        if dev is not None and self.algorithm.intersession_pellet_shift_enabled:
            for val, meth, kind in ((res.pellet_x, dev.set_x, BehaviorEventKind.intersessionShiftX),
                                    (res.pellet_y, dev.set_y, BehaviorEventKind.intersessionShiftY),
                                    (res.pellet_z, dev.set_z, BehaviorEventKind.intersessionShiftZ)):
                if val != 0:
                    meth(val, absolute=False)
                    EventManager.default().post_event_content(kind, context=val)

    def _check_presence_missing(self):
        self._timer_check_missing.cancel()  # in case of
        algo = self._algorithm
        if self._inference.status not in {InferenceStatus.live, InferenceStatus.intersession}:
            algo.presence_missing = False
            return
        if self._analysis.load_cell_monitor.is_engaged:
            algo.presence_missing = False
            return
        # NB: for now the camera presence is not generating any message(s) but only sets multiprocess shared values,
        # so we have to use timer:
        if algo.top_camera_presence_detection.presence_detected:
            algo.presence_missing = False
            new_delay = 0.5  # we can only retry ~soon
        else:
            top_cam_pres_age = time.perf_counter() - algo.top_camera_presence_detection.last_absence_start_perf_c
            top_cam_miss = algo.presence_missing_delay - top_cam_pres_age
            load_cell_miss = algo.presence_missing_delay - self._analysis.load_cell_monitor.disengaged_age
            if top_cam_miss <= 0 and load_cell_miss <= 0:
                algo.presence_missing = True
                new_delay = 0.5  # if camera presence detections goes ON/triggered (shared value only)
            else:
                algo.presence_missing = False
                new_delay = max(top_cam_miss, load_cell_miss)
        new_timer = self._timer_check_missing = _check_missing_timer(new_delay, self._check_presence_missing)
        new_timer.start()

    # region State Machine Requirements
    # Methods required for model_override=True to work.
    def trigger(self):
        pass

    def may_trigger(self):
        pass

    def enter_tunnel(self, *, reason: str="NA"):
        pass

    def may_enter_tunnel(self):
        pass

    def exit_tunnel(self, *, reason: str="NA"):
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
