import os
from enum import Enum
from typing import Dict, Callable, Any, Optional

from transitions import Machine

from autotrainer.core import EventManager, transitions_allow_functions, SystemMessageHandler
from autotrainer.core import ApiEventKind as BehaviorEventKind
from autotrainer.core.multiproc import make_daemon_timer, no_op_timer
from autotrainer.core.logging import get_verbose_logger

from ..behavior_algorithm import BehaviorAlgorithm
from ..pellet_device_protocol import PelletDeviceProtocol
from ..state_machine import StateMachine, StateMachineEvents
from ..system_machine_state import SystemState

logger = get_verbose_logger(__name__)


DEFAULT_LOAD_RETRACT_COUNT_FORCE_HOME = int(os.getenv("AUTOTRAINER_LOAD_RETRACT_COUNT_FORCE_HOME", "12"))


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

    def __init__(
        self,
        algorithm: BehaviorAlgorithm = None,
        msg_handler: SystemMessageHandler = None,
        pellet_device: PelletDeviceProtocol = None,
    ):
        initial_state = PelletState.monitoring

        super().__init__(
            initial_state=initial_state,
            event_names=("pellet_loading", "pellet_sending"),
        )

        # This is primarily for unit testing.  In general, algorithm should always be passed in from the parent
        # SystemMachine.
        if algorithm is None:
            algorithm = BehaviorAlgorithm()
        self._algorithm = algorithm
        algorithm.session_starting += self._session_starting
        algorithm.session_ending += self._session_ending
        algorithm.relay_transitions(self)

        self._message_handler = msg_handler
        if msg_handler is not None:
            msg_handler.ack_received += self._pellet_device_ack_received

        self._pellet_device = pellet_device

        self._api_status_token = None
        self._prev_pellet_seen = None

        self.machine = Machine(
            model=[self],
            states=list(PelletState),
            transitions=self.transitions,
            auto_transitions=False,
            initial=initial_state,
            model_override=True,
        )

        self._cur_timer_try_next_state = no_op_timer
        self._pellet_load_count = 0
        self._pellet_retract_count = 0

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
            self._pellet_load_count += 1
        else:
            self._api_status_token = None

    def before_send_pellet(self):
        if self._pellet_device is not None:
            tot_count = self._pellet_load_count + self._pellet_retract_count
            trigger_count = DEFAULT_LOAD_RETRACT_COUNT_FORCE_HOME
            if 0 < trigger_count <= tot_count:
                # eventual todo: use a configuration value for the threshold
                logger.notice("Forcing a send_home to reset to limits due to load (%s) + retract (%s) "
                              "count greater than threshold (%s)", self._pellet_load_count, self._pellet_retract_count,
                              trigger_count)
                self._pellet_device.send_home()
                self._pellet_load_count = self._pellet_retract_count = 0
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
        can = self.can_use_pellet_command() and self._algorithm.can_send_pellet()
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
    @BehaviorAlgorithm.relay_func
    def _session_starting(self):
        # ensure we reset the diamond triangle drifts measures
        self._algorithm.get_diamond_triangle_drifts(reset=True)
        # Strictly speaking, the pellet should not be covered here when covering is disabled.  Under that condition,
        # must release could be set to False.  However, given how critical it is that the pellet is not covered when
        # disabled, go ahead and request a release under all conditions, even though it should be a no-op in that
        # instance.
        # self._try_next_state(pellet_seen=True, must_release=True, caller="session_starting")
        # this was forcing a release pellet,
        # but is now controlled via receiving camera capture status == RECORDING
        # and not releasing before the desired threshold/delay.

    @BehaviorAlgorithm.relay_func
    def _session_ending(self):
        # todo: this entire func/block should be moved to system machine or behavior algo imho
        algo = self._algorithm
        logger.debug("_session_ending() called ; session_mouse_seen=%s",
                     algo.session_mouse_seen)
        dev = self._pellet_device
        # optional apply of measured motor drifts,
        drifts = algo.get_diamond_triangle_drifts(reset=True)  # always, to reset the recorded values list too.
        if dev is not None:
            correct_drift = algo.auto_correct_motors_drift
            if drifts is not None and correct_drift:
                dev.set_motors_drift(drifts)
            if not (algo.session_mouse_seen and algo.intersession_enabled):
                # force also a send_pellet, only if not gonna go to intersession
                logger.debug("forcing a dev.send_pellet() to ensure XYZ are correct before next state")
                dev.send_pellet()
                # otherwise there is a retract pellet which is executed with next/following try_next_state.
                # NB: not entirely sure we need this here as it is.
                #
        # execute try next state AFTER having applied motor drifts,
        # given next state will move/send the pellet back to deliver/SEND position
        self._try_next_state(caller="session_ending")

    def _move_retract(self):
        logger.debug("calling dev.send_retract()")
        self._pellet_device.send_retract()
        self._pellet_retract_count += 1

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

    @BehaviorAlgorithm.relay_func
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
                "try_next_state cur=%s from %s: %s -> in_session=%s pellet_seen=%s triangle_recently_seen=%s "
                "session_mouse_seen=%s session_pellet_count=%s must_release=%s "
                "pellet_state=%s algo_system_state=%s intersession_state=%s "
                "pellet_seen_age=%.1f" "sec hands_near_pellet_seen=%s"
                , cur_state, caller, reason, algo.is_in_session, pellet_seen, algo.triangle_recently_seen,
                algo.session_mouse_seen, algo.session_pellet_count, must_release,
                self._state, algo.system_state, algo.intersession_state,
                algo.pellet_seen_age, algo.hands_near_pellet_seen,
            )

        def log_could_retry_shortly():
            # retry shortly currently disabled.
            nonlocal reason, retrying
            retrying = True
            reason = f"would have retried shortly {reason}"
            logit()

        if algo.algo_paused:
            return

        cur_state = self.state

        # Always arrest to the retract position during intersession.
        if algo.system_state == SystemState.intersession:
            if cur_state != PelletState.retract:
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
            if algo.can_cover_pellet():
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
                    reason = "release_pellet_when_seen_and_can_release"
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
                if must_release and pellet_seen:
                    reason = "release_when_in_session_and_must_release"
                    if self.can_use_pellet_command():
                        # and algo.can_release_pellet():
                        # actually no need check algo.can_release_pellet(),
                        # it's already done by next release_pellet() as a pre-condition of the defined trigger
                        # in the pellet machine defined transitions.
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

    # Note that transitions have conditions, where applicable.  What may appear to be unconditional calls to cover,
    # release, or otherwise perform pellet transitions will not succeed and perform those actions if these conditions
    # are met.
    transitions = transitions_allow_functions([
        dict(
            trigger=load_pellet,
            source=[PelletState.monitoring, PelletState.covering, PelletState.retract],
            dest=PelletState.loading,
            before=before_load_pellet,
            after=after_load_pellet,
            conditions=can_load_pellet,
        ),

        dict(
            trigger=send_pellet,
            source=[PelletState.loading, PelletState.home, PelletState.prerelease, PelletState.retract],
            dest=PelletState.sending,
            before=before_send_pellet,
            conditions=can_send_pellet,
        ),

        dict(
            trigger=prerelease_pellet,
            source=[PelletState.loading, PelletState.home, PelletState.retract],
            dest=PelletState.prerelease,
            before=before_prerelease_pellet,
            conditions=can_prerelease_pellet,
        ),

        dict(
            trigger=cover_pellet,
            source=[PelletState.monitoring, PelletState.retract],
            dest=PelletState.covering,
            before=before_cover_pellet,
            conditions=can_cover_pellet,
        ),

        dict(
            trigger=release_pellet,
            source=[PelletState.covering, PelletState.monitoring],
            dest=PelletState.releasing,
            before=before_release_pellet,
            conditions=can_release_pellet,
        ),

        dict(
            trigger=monitor_pellet,
            source="*",
            dest=PelletState.monitoring,
        ),

        dict(
            trigger=move_home,
            source="*",
            dest=PelletState.home,
            before=before_move_home,
            conditions=can_move_home,
        ),

        dict(
            trigger=move_retract,
            source=(
                PelletState.loading,  # not sure
                PelletState.sending,  # not sure
                PelletState.releasing,
                PelletState.prerelease,
                PelletState.covering,
                PelletState.monitoring,
            ),
            dest=PelletState.retract,
            after=_move_retract,
        ),
    ])
