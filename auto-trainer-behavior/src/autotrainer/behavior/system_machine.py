from itertools import chain
from pathlib import Path
from threading import Timer
from typing import Optional

from transitions import Machine

from autotrainer.core import (ProjectInfo, EventManager, MessageHandler, SensorAnalysis, LoadCellMonitor,
                              HeadbarPressureMonitor)
from autotrainer.core import Offset3DTuple
from autotrainer.core.logging import get_verbose_logger
from autotrainer.inference import PoseResponse
from autotrainer.core.pose_elements import SceneElement
from . import IntersessionState

from .analysis.intersession_process import IntersessionResponse
from .behavior_algorithm import BehaviorAlgorithm, BehaviorProps
from .behavior_event_kind import BehaviorEventKind
from .inference_protocol import InferenceProtocol
from .intersession import IntersessionMachine
from .pellet import PelletMachine, PelletState
from .pellet_device_protocol import PelletDeviceProtocol
from .state_machine import StateMachine
from .system_machine_state import SystemState
from .tunnel_device_protocol import TunnelDeviceProtocol

logger = get_verbose_logger(__name__)


# NB: this is to ensure we can patch the exact desired one (and only that one) from tests:
_clean_raw_data_timer = Timer
_auto_clamp_release_timer = Timer
_pellet_loading_timer = Timer
#




class SystemMachine(StateMachine):
    states = [e for e in SystemState]

    transitions = [
        {"trigger": "enter_tunnel", "source": SystemState.cage, "dest": SystemState.tunnel,
         "before": "before_enter_tunnel", "after": "after_enter_tunnel"},
        {"trigger": "enter_tunnel", "source": SystemState.tunnel, "dest": SystemState.tunnel,
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

        self._project_info = project_info

        self._timer1 = None  # misc timer

        algorithm = self._algorithm = algorithm if algorithm is not None else BehaviorAlgorithm()
        algorithm.project = project_info
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
            if inference.pose_algorithm is not None:
                inference.pose_algorithm.pose_changed += self._pose_changed
            inference.detection_result_ready += self._handle_detection_result

        self._pellet_device = pellet_device

        self._pellet_machine = PelletMachine(self.algorithm, msg_handler, pellet_device)
        self._pellet_machine.events.pellet_loading += self._pellet_loading
        self._pellet_machine.events.pellet_sending += self._pellet_sending
        self._pellet_machine.events.state_changed += self._pellet_state_changed

        self._intersession = IntersessionMachine(self.algorithm, self._project_info, inference)
        self._intersession.events.on_analysis_ended += self._intersession_ended

        self.machine = Machine(
            model=[self], states=SystemMachine.states, transitions=SystemMachine.transitions,
            auto_transitions=False, initial=initial_state, model_override=True,
        )

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

    def before_enter_tunnel(self):
        EventManager.default().post_event_content(BehaviorEventKind.tunnelEnter)

        self.algorithm.reset_session_pellet_count()

        if self._pellet_machine.state in {
            PelletState.sending,
            PelletState.covering,
            PelletState.releasing,
            PelletState.monitoring,
            PelletState.retract,
        }:
            self._algorithm.start_session()

        self._update_magnet_position(self.algorithm.baseline_intensity)

        self._algorithm.system_state = SystemState.tunnel

    def after_enter_tunnel(self):
        if self._analysis is not None:
            self._evaluate_auto_clamp(self._analysis.headbar_pressure_monitor.is_engaged)

    def before_exit_tunnel(self):
        self._algorithm.system_state = SystemState.cage

    def after_exit_tunnel(self):
        self._update_magnet_position(self.algorithm.baseline_intensity)

        EventManager.default().post_event_content(BehaviorEventKind.tunnelExit)
        self.algorithm.end_session()

    def before_enter_intersession(self):
        # current system_state should be tunnel here
        self._algorithm.system_state = SystemState.intersession

    def after_enter_intersession(self):
        self._intersession.perform_segmentation()

    def before_exit_intersession_to_cage(self):
        self._algorithm.system_state = SystemState.cage
        self._pellet_machine.environment_changed()

    def before_exit_intersession_to_tunnel(self):
        self.state = SystemState.tunnel
        self._algorithm.system_state = SystemState.tunnel
        self.enter_tunnel()
        self._pellet_machine.environment_changed()

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

        can_perform_analysis = algo.can_perform_intersession_analysis()
        if can_perform_analysis and self.state in {
            SystemState.tunnel,
            SystemState.cage,
        }:
            self.enter_intersession()
        else:
            inference = self._inference
            if inference is not None:
                if self._intersession.state != IntersessionState.idle:
                    logger.verbose(
                        "intersession state not idle: %s in progress, not setting inference back to online. "
                        "segment_config=%s detection_config=%s",
                        self._intersession.state,
                        self._intersession._segmentation_configuration,
                        self._intersession._detection_configuration,
                    )
                else:
                    inference.set_inference_to_online()
            # self.exit_intersession()
        if not algo.session_mouse_seen and project is not None:
            if algo.clean_raw_data_on_inactive_session:
                self._clean_raw_data(project)

    def _intersession_ended(self):
        if self.state == SystemState.intersession:
            logger.debug("_intersession_ended: load_cell.engaged=%s", self._analysis.load_cell_monitor.is_engaged)
            if self._analysis.load_cell_monitor.is_engaged:
                self.exit_intersession_to_tunnel()
            else:
                self.exit_intersession_to_cage()

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
            if value:
                if self.state == SystemState.cage:
                    self.enter_tunnel()
                else:
                    EventManager.default().post_event_content(BehaviorEventKind.headfixLoadCellChangedWrongState,
                                                              context=self.state)
            else:
                if self.state == SystemState.tunnel:
                    logger.info("%s False, exiting tunnel ..", LoadCellMonitor.IS_ENGAGED_PROPERTY)
                    self.exit_tunnel()
                else:
                    EventManager.default().post_event_content(BehaviorEventKind.headfixLoadCellChangedWrongState,
                                                              context=self.state)

    def _evaluate_auto_clamp(self, is_headbar_pressure_engaged: bool):
        if not self.algorithm.head_fixation_enabled:
            logger.info(f"auto-clamp disabled (no action taken)")
            return

        logger.info(f"headbar pressure engaged: {is_headbar_pressure_engaged}")

        if not is_headbar_pressure_engaged:
            logger.info(f"auto-clamp force detector not engaged (no action taken)")
            return

        logger.info(f"\tsystem state: {self.state}")

        if self.state == SystemState.tunnel:
            if self._tunnel_device is not None:
                logger.info(f"\tauto-clamp setting position to {self.algorithm.auto_clamp_intensity}")
                self._update_magnet_position(self.algorithm.auto_clamp_intensity)
                EventManager.default().post_event_content(BehaviorEventKind.headFixationEnabled)
            else:
                logger.warning("\tauto-clamp position not sent (head fix command is none)")
        else:
            logger.debug("\tauto-clamp position not sent (not in tunnel)")

    def _load_cell_tare_requested(self):
        if self.state != SystemState.tunnel:
            self._tunnel_device.tare_load_cell()
            EventManager.default().post_event_content(BehaviorEventKind.headfixAutoTare)
        return False

    def _handle_diamond_triangle_offset_changed(self, offset: Optional[Offset3DTuple]):
        if (
            offset is not None
            and self._state != SystemState.intersession
            and self._pellet_machine.state == PelletState.monitoring
            and self._pellet_machine.can_use_pellet_command()
        ):
            self._algorithm.handle_diamond_triangle_offset(offset)

    def _handle_star_triangle_offset_changed(self, offset: Optional[Offset3DTuple]):
        if offset is None:
            return
        pellet_machine = self._pellet_machine
        if not pellet_machine.can_use_pellet_command():
            # never consider any release or cover check when pellet cannot be used yet.
            return
        algo = self.algorithm
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

    def _pose_changed(self, response: PoseResponse):
        if response.pellet_seen:
            self._handle_diamond_triangle_offset_changed(
                response.get_parts_3d_offset(SceneElement.Diamond, SceneElement.Triangle))
            self._handle_star_triangle_offset_changed(
                response.get_parts_3d_offset(SceneElement.Star, SceneElement.Triangle))
        #
        self._algorithm.pellet_seen(response.pellet_seen)
        self._algorithm.mouse_seen(response.mouse_seen)
        if not self._algorithm.pellet_delivery_enabled:
            return
        self._pellet_machine.pellet_seen(response.pellet_seen)

    def _algorithm_property_changed(self, name: str, new_value, _):
        # Always back off to the baseline intensity when auto-clamp is disabled.
        if name == "head_fixation_enabled":
            if not new_value:
                logger.debug("auto-clamp disabled (backing off to baseline intensity)")
                if self.algorithm.is_in_session:
                    logger.debug("\tsending tone to indicate auto-clamp disabled")
                    self._pellet_device.play_tone(self.algorithm.auto_clamp_release_tone_freq, 0.5)
                if self._tunnel_device is not None:
                    logger.debug(
                        f"\tchanging magnet intensity to baseline in {self.algorithm.auto_clamp_release_delay} seconds")
                    timer = _auto_clamp_release_timer(self.algorithm.auto_clamp_release_delay,
                                  lambda: self._update_magnet_position(self.algorithm.baseline_intensity))
                    timer.start()
        elif name == BehaviorProps.PELLET_MOTOR_DRIFT:
            if new_value is not None:
                self._pellet_device.set_motor_drift(new_value)

    def _update_magnet_position(self, position: int):
        if self._tunnel_device is not None:
            self._tunnel_device.update_head_magnet_intensity(position)

    def _pellet_loading(self):
        prev_t1 = self._timer1
        if prev_t1 is None or prev_t1.finished.is_set():
            self._timer1 = _pellet_loading_timer(5, self._consider_end_session)
            self._timer1.start()
        else:
            logger.verbose("%s: prev timer not finished for pellet loading ; prev_timer=%s", self, prev_t1)

    def _pellet_sending(self):
        if self.state == SystemState.tunnel:
            self.algorithm.start_session()

    def _pellet_state_changed(self, old_value, new_value):
        logger.info("pellet_state_changed: %s -> %s", old_value, new_value)

    def _consider_end_session(self):
        # Do not end if the mouse is still in the tunnel and (a pellet is seen or the pellet deliver is in the sending
        # or releasing states).  Otherwise, there will be no trigger to start a new session and recording (tunnel entry
        # or sending the pellet)
        if (self.state == SystemState.tunnel
                and self._pellet_machine.state in {
                    PelletState.sending, PelletState.releasing, PelletState.monitoring,
                    # PelletState.loading,
                }
        ):
            return

        self.algorithm.end_session()

    def _handle_detection_result(self, res: IntersessionResponse):
        if res.food_consumed > 0:
            self._algorithm.day_pellet_count += res.food_consumed
            self._algorithm.session_pellet_count += res.food_consumed
        if res.successful_reaches > 0:
            self._algorithm.successful_reaches = res.successful_reaches
        if res.pellets_presented > 0:
            self._algorithm.pellets_presented = res.pellets_presented
        dev = self._pellet_device
        if dev is not None:
            for val, meth, kind in ((res.pellet_x, dev.set_x, BehaviorEventKind.intersessionShiftX),
                                    (res.pellet_y, dev.set_y, BehaviorEventKind.intersessionShiftY),
                                    (res.pellet_z, dev.set_z, BehaviorEventKind.intersessionShiftZ)):
                if val != 0:
                    meth(val, absolute=False)
                    EventManager.default().post_event_content(kind, context=val)

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
