import logging
import threading
import time
from enum import Enum
from typing import Dict, Callable, Any, Optional

from events import Events
from transitions import Machine

from autotrainer.core.logging import get_verbose_logger
from autotrainer.core import EventManager, MessageHandler, ObservableObject, Offset3DTuple, Motor

from ..behavior_algorithm import BehaviorAlgorithm
from ..behavior_event_kind import BehaviorEventKind
from ..pellet_device_protocol import PelletDeviceProtocol
from ..state_machine import StateMachine, StateMachineEvents
from ..system_machine_state import SystemState

logger = get_verbose_logger(__name__)


class PelletState(str, Enum):
    monitoring = "monitoring"
    loading = "loading"
    prerelease = "prerelease"
    sending = "sending"
    releasing = "releasing"
    covering = "covering"
    home = "home"
    retract = "retract"


class PelletMachineEvents(StateMachineEvents):
    pellet_loading: Callable[[], None]
    pellet_sending: Callable[[], None]


class PelletMachine(StateMachine):

    _events_class = PelletMachineEvents

    # Note that transitions have conditions, where applicable.  What may appear to be unconditional calls to cover,
    # release, or otherwise perform pellet transitions will not succeed and perform those actions if these conditions
    # are met.
    transitions = [
        {"trigger": "load_pellet", "source": [PelletState.monitoring, PelletState.covering, PelletState.retract],
         "dest": PelletState.loading, "before": "before_load_pellet", "after": "after_load_pellet",
         "conditions": "can_load_pellet"},

        {"trigger": "send_pellet", "source": [PelletState.loading, PelletState.home, PelletState.prerelease, PelletState.retract],
         "dest": PelletState.sending, "before": "before_send_pellet", "conditions": "can_send_pellet"},

        dict(
            trigger="prerelease_pellet",
            source=[PelletState.loading, PelletState.home, PelletState.retract], dest=PelletState.prerelease,
            before="before_prerelease_pellet",
            conditions="can_prerelease_pellet",
        ),

        dict(
            trigger="cover_pellet", source=[PelletState.monitoring, PelletState.retract], dest=PelletState.covering,
            before="before_cover_pellet", conditions="can_cover_pellet",
        ),

        {"trigger": "release_pellet", "source": [PelletState.covering, PelletState.monitoring],
         "dest": PelletState.releasing, "before": "before_release_pellet",
         "conditions": "can_release_pellet"},
        {"trigger": "monitor_pellet", "source": "*", "dest": PelletState.monitoring},
        {"trigger": "move_home", "source": "*", "dest": PelletState.home, "before": "before_move_home",
         "conditions": "can_move_home"},
        dict(
            trigger="move_retract",
            source=(
                PelletState.loading,  # not sure
                PelletState.sending,  # not sure
                PelletState.releasing,
                PelletState.prerelease,
                PelletState.covering,
                PelletState.monitoring,
            ),
            dest=PelletState.retract,
            after="_move_retract",
        ),
    ]

    def __init__(self, algorithm: BehaviorAlgorithm = None, msg_handler: MessageHandler = None,
                 pellet_device: PelletDeviceProtocol = None,
                 ):

        initial_state = PelletState.monitoring

        super().__init__(
            initial_state=initial_state,
            event_names=("pellet_loading", "pellet_sending"),
        )

        # This is primarily for unit testing.  In general, algorithm should always be passed in from the parent
        # SystemMachine.
        self._algorithm = algorithm if algorithm is not None else BehaviorAlgorithm()

        self._algorithm.session_starting += self._session_starting
        self._algorithm.session_ending += self._session_ending

        self._message_handler = msg_handler
        if msg_handler is not None:
            msg_handler.ack_received += self._pellet_device_ack_received

        self._pellet_device = pellet_device

        self._api_status_token = None
        self._prev_pellet_seen = None

        self.machine = Machine(model=[self], states=list(PelletState),
                               transitions=PelletMachine.transitions, auto_transitions=False,
                               initial=initial_state, model_override=True,
                       )

        self._cur_timer_try_next_state: Optional[threading.Timer] = None

    @property
    def algorithm(self):
        return self._algorithm

    @property
    def events(self):
        return self._events

    def before_move_home(self):
        if self._pellet_device is not None:
            self._api_status_token = self._pellet_device.send_home()
            EventManager.default().post_event_content(BehaviorEventKind.pelletHomeBegin, context=self._api_status_token)
        else:
            self._api_status_token = None

    def before_load_pellet(self):
        if self._pellet_device is not None:
            self.events.pellet_loading()
            self._api_status_token = self._pellet_device.load_pellet()
            EventManager.default().post_event_content(BehaviorEventKind.pelletLoadBegin, context=self._api_status_token)
        else:
            self._api_status_token = None

    def before_send_pellet(self):
        if self._pellet_device is not None:
            self.events.pellet_sending()
            self._api_status_token = self._pellet_device.send_pellet()
            EventManager.default().post_event_content(BehaviorEventKind.pelletSendBegin, context=self._api_status_token)
        else:
            self._api_status_token = None

    def before_prerelease_pellet(self):
        if self._pellet_device is not None:
            self._api_status_token = self._pellet_device.release_pellet()
            EventManager.default().post_event_content(BehaviorEventKind.pelletPrereleaseBegin, context=self._api_status_token)
        else:
            self._api_status_token = None

    def after_load_pellet(self):
        self._algorithm.pellet_loaded()

    def before_cover_pellet(self):
        if self._pellet_device is not None:
            self._api_status_token = self._pellet_device.cover_pellet()
            EventManager.default().post_event_content(BehaviorEventKind.pelletCoverBegin, context=self._api_status_token)
        else:
            self._api_status_token = None

    def before_release_pellet(self):
        if self._pellet_device is not None:
            self._api_status_token = self._pellet_device.release_pellet()
            EventManager.default().post_event_content(BehaviorEventKind.pelletReleaseBegin, context=self._api_status_token)
        else:
            self._api_status_token = None

    def can_move_home(self):
        can = self.can_use_pellet_command()
        EventManager.default().post_event_content(BehaviorEventKind.pelletHomeCan, context=can)
        return can

    def can_load_pellet(self):
        can = self.can_use_pellet_command() and self._algorithm.can_load_pellet()
        EventManager.default().post_event_content(BehaviorEventKind.pelletLoadCan, context=can)
        return can

    def can_send_pellet(self):
        can = self.can_use_pellet_command()
        EventManager.default().post_event_content(BehaviorEventKind.pelletSendCan, context=can)
        return can

    def can_cover_pellet(self):
        can = self.can_use_pellet_command() and self._algorithm.can_cover_pellet()
        EventManager.default().post_event_content(BehaviorEventKind.pelletCoverCan, context=can)
        return can

    def can_prerelease_pellet(self):
        can = self.can_use_pellet_command()
        EventManager.default().post_event_content(BehaviorEventKind.pelletPrereleaseCan, context=can)
        return can

    def can_release_pellet(self):
        can = self.can_use_pellet_command() and self._algorithm.can_release_pellet()
        EventManager.default().post_event_content(BehaviorEventKind.pelletReleaseCan, context=can)
        return can

    def can_use_pellet_command(self):
        return self._api_status_token is None

    def pellet_seen(self, seen: bool):
        self._try_next_state(seen, caller="pellet_seen")

    # region Callbacks
    def _session_starting(self):
        pass
        # Strictly speaking, the pellet should not be covered here when covering is disabled.  Under that condition,
        # must release could be set to False.  However, given how critical it is that the pellet is not covered when
        # disabled, go ahead and request a release under all conditions, even though it should be a no-op in that
        # instance.
        # if self._pellet_device is not None:
        #     self._pellet_device.delay(1)
        # this can be called right when cameras have been requested to start,
        # but camera start is done async, so give a small delay before trying next state,
        # which would be send_pellet+release pellet,
        # but could be missed in the video recording given async start of the cams recording.
        # self._try_next_state(True, True, caller="session_starting")
        # cur_timer = self._cur_timer_try_next_state
        # if cur_timer is not None:
        #     cur_timer.cancel()
        # # safety backup measure:
        # cur_timer = self._cur_timer_try_next_state = threading.Timer(1.5,
        #     lambda: self._try_next_state(True, True, caller="timer_session_starting", from_timer=True))
        # cur_timer.start()

    def _session_ending(self):
        algo = self._algorithm
        logger.verbose("%s: _session_ending() called", self)
        dev = self._pellet_device
        # optional apply of measured motor drifts,
        drifts = algo.get_diamond_triangle_drifts(reset=True)  # always, to reset the recorded values list too.
        if dev is not None:
            correct_drift = algo.auto_correct_motors_drift
            if drifts is not None and correct_drift:
                # not sure for:
                # flips = dev.get_motor_flips()
                # drifts *= flips
                dev.set_motors_drift(drifts)
            if not (algo.session_mouse_seen and algo.intersession_enabled):
                # force also a send_pellet, only if not gonna go to intersession
                dev.send_pellet()
                # otherwise there is a retract pellet which is executed with next/following try_next_state.
        # execute try next state AFTER having applied motor drifts,
        # given next state will move/send the pellet back to deliver/SEND position
        self._try_next_state(caller="session_ending")

    def _move_retract(self):
        self._pellet_device.send_retract()

    def _pellet_device_ack_received(self, token: Optional[str]):
        if token is not None:
            logger.debug("pellet_ack_received: %s", token)

        if self._api_status_token is None:
            # External command.  Safe to ignore.
            return

        if token != self._api_status_token:
            # External command while we are waiting for our own.  Track in case it is causing conflicts.
            EventManager.default().post_event_content(BehaviorEventKind.pelletExternalToken, context=token)
            logger.debug("ignoring pellet delivery token from external command. token=%r api_status=%r",
                         token, self._api_status_token)
            return

        EventManager.default().post_event_content(BehaviorEventKind.pelletAcknowledgeToken, context=token)

        self._api_status_token = None

        self._try_next_state(caller="pellet_device_ack_received")

    # endregion

    def _try_next_state(
        self,
        pellet_seen: bool = True,
        must_release: bool = False,
        *,
        caller: str = "not-provided",
        from_timer: bool = False,
    ):
        # always use the thread lock, given this can be called from different threads at the same time,
        # so possibly completely intermixed/leaved, which we want to protect from, so:
        with self._algorithm.thread_lock:
            self.__try_next_state(pellet_seen, must_release,
                                  caller=caller, is_from_timer=from_timer)

    environment_changed = _try_next_state  # remove 1 unnecessary stack level

    def __try_next_state(
        self,
        pellet_seen: bool = True,
        must_release: bool = False,
        *,
        caller: str,
        is_from_timer: bool = False,
    ):
        cur_timer = self._cur_timer_try_next_state
        if cur_timer is not None:
            cur_timer.cancel()

        algo = self._algorithm
        reason: str = "unknown"
        retrying = False

        def logit():
            if is_from_timer:
                func = logger.notice
            elif retrying:
                func = logger.spam if reason != "release_when_sent_cover_enabled" else logger.debug
            else:
                func = logger.verbose
            func(
                "try_next_state from %s (timer=%s): %s -> in_session=%s pellet_seen=%s triangle_recently_seen=%s "
                "session_mouse_seen=%s session_pellet_count=%s must_release=%s "
                "pellet_state=%s algo_system_state=%s intersession_state=%s",
                caller, is_from_timer, reason, algo.is_in_session, pellet_seen, algo.triangle_recently_seen,
                algo.session_mouse_seen, algo.session_pellet_count, must_release,
                self._state, algo.system_state, algo.intersession_state,
            stacklevel=3)

        def log_could_retry_shortly():
            # retry shortly currently disabled.
            nonlocal reason, retrying
            retrying = True
            reason = f"would have retried shortly {reason}"
            logit()

        # Always arrest to the retract position during intersession.
        if algo.system_state == SystemState.intersession:
            if self.state != PelletState.retract:
                covering_retrying = False
                if algo.can_cover_pellet():
                    reason = "cover_pellet_before_retract_when_intersession"
                    if self.can_use_pellet_command():
                        logit()
                        # Need monitoring state to be able to cover_pellet, atm,
                        self.state = PelletState.monitoring
                        # alternatively we could simply allow this states transition.
                        self.cover_pellet()
                    else:
                        log_could_retry_shortly()
                        # covering_retrying = True
                        # given retry disabled atm.

                # could also decide to execute the move_retract before the cover_pellet.
                if not covering_retrying:
                    # only if not covering_retrying
                    reason = "move_retract_when_intersession"
                    logit()
                    self.move_retract()
            return

        cur_state = self.state

        if cur_state in {PelletState.loading, PelletState.retract}:
            if algo.can_cover_pellet():
                reason = "send_pellet_when_loaded_or_retract_not_intersession"
                if self.can_use_pellet_command():
                    logit()
                    self.send_pellet()
                else:
                    log_could_retry_shortly()
            else:
                reason = "prerelease_when_load_or_retract"
                if self.can_use_pellet_command():
                    logit()
                    self.prerelease_pellet()
                else:
                    log_could_retry_shortly()

        elif cur_state == PelletState.prerelease:
            reason = "send_pellet_when_prereleased"
            if self.can_send_pellet():
                logit()
                self.send_pellet()
            else:
                log_could_retry_shortly()

        elif cur_state == PelletState.sending:
            if algo.pellet_cover_enabled:
                reason = "release_when_sent_cover_enabled"
                if self.can_use_pellet_command():
                    logit()
                    # Put things in a consistent state of covering without sending an unnecessary command.
                    self.state = PelletState.covering
                    # alternatively we could simply allow this states transition
                    self.release_pellet()
                else:
                    log_could_retry_shortly()
            else:
                reason = "monitor_when_send_cover_not_enabled"
                logit()
                self.monitor_pellet()

        elif cur_state == PelletState.covering:
            if not pellet_seen:
                if algo.triangle_recently_seen:
                    reason = "load_pellet_when_covered_and_pellet_not_seen"
                    if self.can_load_pellet():
                        logit()
                        self.load_pellet()
                    else:
                        log_could_retry_shortly()
            else:
                if algo.can_release_pellet():
                    reason = "send_pellet_when_seen_and_can_release"
                    if self.can_use_pellet_command():
                        logit()
                        self.release_pellet()
                    else:
                        log_could_retry_shortly()

        elif cur_state == PelletState.releasing:
            reason = "monitor_when_released"
            logit()
            self.monitor_pellet()

        elif cur_state == PelletState.home:
            reason = "send_pellet_when_home"
            if self.can_use_pellet_command():
                logit()
                self.send_pellet()
            else:
                log_could_retry_shortly()

        elif cur_state == PelletState.monitoring:
            if algo.is_in_session:
                if must_release:  #  or (pellet_seen and self.can_release_pellet()):
                    reason = "release_when_in_session_and_must_release"
                    if self.can_use_pellet_command():
                        logit()
                        self.release_pellet()
                    else:
                        log_could_retry_shortly()
                elif (not pellet_seen and algo.triangle_recently_seen) or algo.is_triangle_pellet_distance_too_far():
                    reason = "load_pellet_when_insession_pellet_not_seen_or_too_far"
                    if self.can_load_pellet():
                        logit()
                        self.load_pellet()
                    else:
                        log_could_retry_shortly()
            else:
                if (not pellet_seen or algo.is_triangle_pellet_distance_too_far()) and algo.triangle_recently_seen:
                    if algo.can_load_pellet():
                        reason = "load_pellet_in_monitoring"
                        if self.can_use_pellet_command():
                            logit()
                            self.load_pellet()
                        else:
                            log_could_retry_shortly()
                elif pellet_seen:
                    if algo.can_cover_pellet():
                        reason = "cover_pellet_in_monitoring"
                        if self.can_use_pellet_command():
                            logit()
                            self.cover_pellet()
                        else:
                            log_could_retry_shortly()
        else:
            logger.warning("unknown state: %s", cur_state)

    # region State Machine Requirements
    # Methods required for model_override=True to work.
    def trigger(self):
        pass

    def may_trigger(self):
        pass

    def move_home(self):
        pass

    def may_move_home(self):
        pass

    def move_retract(self):
        """Trigger a "move" to retract position (y - 10 relative)"""

    def may_move_retract(self):
        pass

    def load_pellet(self):
        pass

    def may_load_pellet(self):
        pass

    def prerelease_pellet(self):
        pass

    def may_prerelease_pellet(self):
        pass

    def send_pellet(self):
        pass

    def may_send_pellet(self):
        pass

    def release_pellet(self):
        pass

    def may_release_pellet(self):
        pass

    def cover_pellet(self):
        pass

    def may_cover_pellet(self):
        pass

    def monitor_pellet(self):
        pass

    def may_monitor_pellet(self):
        pass

    def is_home(self):
        pass

    def is_loading(self):
        pass

    def is_prerelease(self):
        pass

    def is_sending(self):
        pass

    def is_covering(self):
        pass

    def is_releasing(self):
        pass

    def is_monitoring(self):
        pass

    def is_retract(self):
        pass

    # endregion
