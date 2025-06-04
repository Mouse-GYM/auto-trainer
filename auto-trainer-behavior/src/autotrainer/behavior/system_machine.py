import logging
from enum import Enum
from threading import Timer
from typing import Optional

from transitions import Machine

from autotrainer.core import ProjectInfo, EventManager, MessageHandler, SensorAnalysis, LoadCellMonitor, \
    HeadbarPressureMonitor
from autotrainer.inference import PoseResponse
from .analysis.intersession_process import IntersessionResponse
from .behavior_algorithm import BehaviorAlgorithm
from .behavior_event_kind import BehaviorEventKind
from .inference_protocol import InferenceProtocol
from .intersession import IntersessionMachine
from .pellet import PelletMachine, PelletState
from .pellet_device_protocol import PelletDeviceProtocol
from .state_machine import StateMachine
from .system_machine_state import SystemState
from .tunnel_device_protocol import TunnelDeviceProtocol

logger = logging.getLogger(__name__)


class SystemMachine(StateMachine):
    states = [e for e in SystemState]

    class Properties(str, Enum):
        pass

    transitions = [
        {"trigger": "enter_tunnel", "source": SystemState.cage, "dest": SystemState.tunnel,
         "before": "before_enter_tunnel", "after": "after_enter_tunnel"},
        {"trigger": "exit_tunnel", "source": SystemState.tunnel, "dest": SystemState.cage,
         "before": "before_exit_tunnel", "after": "after_exit_tunnel"},
        {"trigger": "enter_intersession", "source": SystemState.cage, "dest": SystemState.intersession,
         "before": "before_enter_intersession", "after": "after_enter_intersession"},
        {"trigger": "exit_intersession", "source": SystemState.intersession, "dest": SystemState.cage,
         "before": "before_exit_intersession"}
    ]

    def __init__(self,
                 algorithm: Optional[BehaviorAlgorithm] = None,
                 project_info: Optional[ProjectInfo] = None,
                 msg_handler: MessageHandler = None,
                 analysis: SensorAnalysis = None,
                 tunnel_device: TunnelDeviceProtocol = None,
                 pellet_device: PelletDeviceProtocol = None,
                 inference: InferenceProtocol = None):

        initial_state = SystemState.cage
        super().__init__(initial_state=initial_state)

        self._project_info = project_info

        self._algorithm = algorithm if algorithm is not None else BehaviorAlgorithm()
        self._algorithm.project = self._project_info

        self._tunnel_device = tunnel_device

        self._analysis = analysis

        if self._analysis is not None:
            self._analysis.load_cell_monitor.property_changed += self._load_cell_monitor_property_changed
            self._analysis.headbar_pressure_monitor.property_changed += self._headbar_pressure_monitor_property_changed
            self._analysis.load_cell_tare_monitor.tare_callback = self._load_cell_tare_requested

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

        self._algorithm.session_ending += self._session_ended
        self._algorithm.property_changed += self._algorithm_property_changed

        self.machine = Machine(
            model=[self], states=SystemMachine.states, transitions=SystemMachine.transitions,
            auto_transitions=False, initial=initial_state, model_override=True,
        )

    @property
    def algorithm(self):
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
        }:
            self.algorithm.start_session()

        self._update_magnet_position(self.algorithm.baseline_intensity)

        self._algorithm.system_state = SystemState.tunnel

    def after_enter_tunnel(self):
        if self._analysis is not None:
            self._evaluate_auto_clamp(self._analysis.headbar_pressure_monitor.is_engaged)

    def before_exit_tunnel(self):
        self._algorithm.system_state = SystemState.cage
        # inference = self._inference
        # assert isinstance(inference, InferenceModel)
        # inference.set_inference_to_online()

    def after_exit_tunnel(self):
        self._update_magnet_position(self.algorithm.baseline_intensity)

        EventManager.default().post_event_content(BehaviorEventKind.tunnelExit)
        self.algorithm.end_session()

    def before_enter_intersession(self):
        self._algorithm.system_state = SystemState.intersession

    def after_enter_intersession(self):
        self._intersession.perform_segmentation()

    def before_exit_intersession(self):
        self._algorithm.system_state = SystemState.cage
        self._pellet_machine.environment_changed()

    def _session_ended(self):
        # 5/16/25 should not remove auto-clamp at session end for current testing.
        # TODO: make this configurable.
        # if self._tunnel_device is not None:
        #    self._update_magnet_position(self.algorithm.baseline_intensity)

        if self.algorithm.can_perform_intersession_analysis() and self.state == SystemState.cage:
            self.enter_intersession()
        else:
            inference = self._inference
            if inference is not None:
                inference.set_inference_to_online()
            # self.exit_intersession()

    def _intersession_ended(self):
        if self.state == SystemState.intersession:
            self.exit_intersession()

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
            EventManager.default().post_event_content(BehaviorEventKind.headfixLoadCellChangedInIntersession, context=value)
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

    def _pose_changed(self, response: PoseResponse):
        self._algorithm.pellet_seen(response.pellet_seen)
        self._algorithm.mouse_seen(response.mouse_seen)
        if not self._algorithm.pellet_delivery_enabled:
            return
        self._pellet_machine.pellet_seen(response.pellet_seen)

    def _algorithm_property_changed(self, name: str, value, _):
        # Always back off to the baseline intensity when auto-clamp is disabled.
        if name == "head_fixation_enabled":
            if not value:
                logger.debug("auto-clamp disabled (backing off to baseline intensity)")
                if self.algorithm.is_in_session:
                    logger.debug("\tsending tone to indicate auto-clamp disabled")
                    self._pellet_device.play_tone(self.algorithm.auto_clamp_release_tone_freq, 0.5)
                if self._tunnel_device is not None:
                    logger.debug(
                        f"\tchanging magnet intensity to baseline in {self.algorithm.auto_clamp_release_delay} seconds")
                    timer = Timer(self.algorithm.auto_clamp_release_delay,
                                  lambda: self._update_magnet_position(self.algorithm.baseline_intensity))
                    timer.start()

    def _update_magnet_position(self, position: int):
        if self._tunnel_device is not None:
            self._tunnel_device.update_head_magnet_intensity(position)

    def _pellet_loading(self):
        self._timer1 = Timer(2, self._consider_end_session)
        self._timer1.start()

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
            and self._pellet_machine.state in {PelletState.sending, PelletState.releasing, PelletState.monitoring}
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
            for val, meth in ((res.pellet_x, dev.set_x), (res.pellet_y, dev.set_y), (res.pellet_z, dev.set_z)):
                if val != 0:
                    meth(val, absolute=False)

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
