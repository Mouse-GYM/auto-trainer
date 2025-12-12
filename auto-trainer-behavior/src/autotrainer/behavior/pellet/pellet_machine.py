import math
import time
from enum import Enum
from typing import Dict, Callable, Any, Optional

from transitions import Machine

from autotrainer.core import EventManager, transitions_allow_functions, SystemMessageHandler
from autotrainer.core import ApiEventKind as BehaviorEventKind
from autotrainer.core.multiproc import make_daemon_timer, no_op_timer
from autotrainer.core.logging import get_verbose_logger
from .. import IntersessionState

from ..behavior_algorithm import BehaviorAlgorithm
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
    pellet_sending: Callable[[], None]  # now unused
    pellet_sent: Callable[[], None]


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
            event_names=("pellet_loading", "pellet_sending", "pellet_sent"),
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
        self._api_status_token_pellet_send = None
        self._covered_state = None  # False == released ; True == covered ; None == unknown/none
        self._prev_covered_state = None
        self._send_begin_perf_c = -math.inf
        self._send_end_perf_c = -math.inf
        self._prev_pellet_load_perf_c = -math.inf
        self._prev_notify_loaded_perf_c = -math.inf

        self.machine = Machine(
            model=[self],
            states=list(PelletState),
            transitions=self.transitions,
            auto_transitions=False,
            initial=initial_state,
            model_override=True,
        )

        self._cur_timer_try_next_state = no_op_timer

    @property
    def algorithm(self):
        return self._algorithm

    @property
    def events(self) -> PelletMachineEvents:
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
            if self._api_status_token is not None:
                self._prev_pellet_load_perf_c = time.perf_counter()
                self._covered_state = None
            EventManager.default().post_event_content(BehaviorEventKind.pelletLoadBegin, context=self._api_status_token)
        else:
            self._api_status_token = None

    def before_send_pellet(self):
        if self._pellet_device is not None:
            self._api_status_token = self._pellet_device.send_pellet()
            if self._api_status_token is not None:
                self._api_status_token_pellet_send = self._api_status_token
                self._send_begin_perf_c = time.perf_counter()
                self.events.pellet_sending()
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
        pass
        # now handled in try-next-state:
        # self._algorithm.pellet_loaded

    def before_cover_pellet(self):
        if self._pellet_device is not None:
            self._api_status_token = self._pellet_device.cover_pellet()
            if self._api_status_token is not None:
                self._covered_state = True
            EventManager.default().post_event_content(BehaviorEventKind.pelletCoverBegin, context=self._api_status_token)
        else:
            self._api_status_token = None

    def before_release_pellet(self):
        if self._pellet_device is not None:
            self._api_status_token = self._pellet_device.release_pellet()
            if self._api_status_token is not None:
                self._covered_state = False
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
        self.environment_changed(seen, caller="pellet_seen", is_from_inference=True)

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
            self.send_pellet()
            # otherwise there is a retract pellet which is executed with next/following try_next_state.
            # NB: not entirely sure we need this here as it is.
            #
        elif algo.session_mouse_seen and self._state == PelletState.monitoring:
            # sessions ended because exit tunnel, otherwise state would be load_pellet
            self.move_retract()
        # execute try next state AFTER having applied motor drifts,
        # given next state will move/send the pellet back to deliver/SEND position
        # self.environment_changed(caller="session_ending")

    def _before_move_retract(self):
        self._api_status_token = self._pellet_device.send_retract()

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
        perf_now = time.perf_counter()
        if token == self._api_status_token_pellet_send:
            self._send_end_perf_c = perf_now
            self._api_status_token_pellet_send = None
            self.events.pellet_sent()

        # nb: in live we could bypass this call : it's anyway called with live-inference pellet-seen callback..
        self.environment_changed(caller="pellet_device_ack_received")

    def get_send_begin_age(self, perf_now: float):
        return perf_now - self._send_begin_perf_c

    @property
    def pellet_send_begin_age(self) -> float:
        return time.perf_counter() - self._send_begin_perf_c

    def get_send_end_age(self, perf_now: float):
        return perf_now - self._send_end_perf_c

    @property
    def pellet_send_end_age(self) -> float:
        return time.perf_counter() - self._send_end_perf_c

    # endregion

    def _notify_pellet_loaded_ok(self):
        self._prev_notify_loaded_perf_c = time.perf_counter()
        self._algorithm.pellet_loaded()

    @BehaviorAlgorithm.relay_func
    def environment_changed(
        self,
        pellet_seen: bool = True,
        must_release: bool = False,
        *,
        caller: str = "not-provided",
        from_timer: bool = False,
        is_from_inference: bool = False,
    ):
        # always use the thread lock, given this can be called from different threads at the same time,
        # so possibly completely intermixed/leaved, which we want to protect from, so:
        with self._algorithm.thread_lock:
            self.__try_next_state(pellet_seen, must_release,
                                  caller=caller, is_from_timer=from_timer, is_from_inference=is_from_inference)

    def __try_next_state(
        self,
        pellet_seen: bool = True,
        must_release: bool = False,
        *,
        caller: str,
        is_from_timer: bool = False,
        is_from_inference: bool = False,
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
                "try_next_state cur=%s from %s: %s -> in_session=%s pellet_seen=%s recently=%s triangle_recently_seen=%s "
                "session_mouse_seen=%s session_pellet_count=%s must_release=%s "
                "pellet_state=%s algo_system_state=%s intersession_state=%s "
                "pellet_seen_age=%.1f" "sec hands_near_pellet_seen=%s covered_state=%s"
                , cur_state, caller, reason, algo.is_in_session, pellet_seen,
                algo.pellet_recently_seen, algo.triangle_recently_seen,
                algo.session_mouse_seen, algo.session_pellet_count, must_release,
                self._state, algo.system_state, algo.intersession_state,
                algo.pellet_seen_age, algo.hands_near_pellet_seen, self._covered_state,
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

        if algo.system_state == SystemState.intersession:
            if algo.intersession_state == IntersessionState.segmentation and not is_from_inference:
                # waiting inference is back, nothing we can do
                return

        if cur_state in {PelletState.loading, PelletState.retract}:
            if not self.can_use_pellet_command():
                # wait movement is finished
                return
            # this is going to be called at end of intersession after going to detection phase,
            # basically when inference is back to live
            if not pellet_seen and algo.triangle_recently_seen:  # algo.diamond_recently_seen and algo.star_recently_seen:
                # if triangle seen and pellet not seen: pellet not loaded ok for sure, we should see it if it was there
                reason = "load_pellet_when_not_seen_and_retract_or_loading"
                logit()
                self.load_pellet()
            else:
                # either pellet is seen, or we don't know (might be not visible on cameras),
                if cur_state == PelletState.loading and pellet_seen:
                    self._notify_pellet_loaded_ok()
                # current state is either retract or loading (loaded),
                # we can do a send_pellet() but ensure covered(-or-released) is as desired, *before* sending :
                if algo.can_cover_pellet():
                    reason = "cover_when_loaded_or_retract"
                    logit()
                    self.cover_pellet()
                else:
                    reason = "release_when_loaded_or_retract"
                    logit()
                    self.release_pellet()

                #
                # even if pellet is not seen, send it to deliver,
                # the end position of load-pellet sequence might not be (entirely) visibile by camera,
                reason = "send_pellet_when_loaded_or_retract"
                logit()
                # force api status token to None, from eventualy previous release/cover pellet actions.
                self._api_status_token = None  # otherwise cannot send pellet
                self.send_pellet()
                # then always directly:
                self.monitor_pellet()

        elif cur_state == PelletState.sending:
            # normally not anymore necessary, pellet-send is now immediatelly followed by pellet-monitor
            logger.warning("%s: deprecated, should be followed by monitor_pellet", cur_state)
            reason = "monitor_when_sent"
            logit()
            self.monitor_pellet()
            # could probably re-enter immediatelly this func/try_next_state with current passed args ..

        elif cur_state in {PelletState.covering, PelletState.releasing}:
            logger.warning("%s: deprecated, should be followed by send_pellet or monitor_pellet", cur_state)
            # maybe not anymore necessary/needed, same as above
            self.monitor_pellet()

        elif cur_state == PelletState.home:
            # not used, could probably remove
            reason = "send_pellet_when_home"
            if self.can_send_pellet():
                logit()
                self.send_pellet()
                self.monitor_pellet()
                # could probably re-enter immediatelly this func/try_next_state with current passed args ..
            else:
                log_could_retry_shortly()

        elif cur_state == PelletState.monitoring:

            # previous load-pellet could have missed to notify for pellet-loaded event,
            # if/when pellet is not visible at end of load-pellet sequence. So have to recheck here:
            if pellet_seen and self._prev_notify_loaded_perf_c < self._prev_pellet_load_perf_c:
                self._notify_pellet_loaded_ok()

            if ((not pellet_seen and algo.triangle_recently_seen)
                  or (pellet_seen and algo.triangle_recently_seen and algo.is_triangle_pellet_distance_too_far())
            ):
                reason = "load_pellet_when_insession_pellet_not_seen_or_too_far"
                if self.can_load_pellet():
                    logit()
                    self.load_pellet()
                else:
                    log_could_retry_shortly()
                return
            if self._prev_covered_state is not self._covered_state:
                logger.debug("covered_state: %s -> %s", self._prev_covered_state, self._covered_state)
                self._prev_covered_state = self._covered_state
            if not algo.can_cover_pellet() or algo.can_release_pellet():
                # NB: also having to use algo.can_cover_pellet(), given can_release_pellet() depends on conditions
                if self._covered_state is not False:
                    # nb: keep this second if not grouped with the previous one,
                    # otherwise cover will continuously switch between covered and released.
                    reason = "release_pellet_in_monitoring"
                    if self.can_use_pellet_command():
                        logit()
                        self.release_pellet()
                        self.monitor_pellet()
                    else:
                        log_could_retry_shortly()
            elif algo.can_cover_pellet() and self._covered_state is not True:
                reason = "cover_pellet_in_monitoring"
                if self.can_use_pellet_command():
                    logit()
                    self.cover_pellet()
                    self.monitor_pellet()
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
            source=[PelletState.loading, PelletState.monitoring, PelletState.covering, PelletState.retract],
            dest=PelletState.loading,
            before=before_load_pellet,
            after=after_load_pellet,
            conditions=can_load_pellet,
        ),

        dict(
            trigger=send_pellet,
            source=[PelletState.loading, PelletState.covering, PelletState.releasing, PelletState.home, PelletState.prerelease, PelletState.retract],
            dest=PelletState.sending,
            before=before_send_pellet,
            conditions=can_send_pellet,
        ),

        dict(
            # now unused
            trigger=prerelease_pellet,
            source=[PelletState.loading, PelletState.home, PelletState.retract],
            dest=PelletState.prerelease,
            before=before_prerelease_pellet,
            conditions=can_prerelease_pellet,
        ),

        dict(
            trigger=cover_pellet,
            source=[PelletState.loading, PelletState.monitoring, PelletState.retract],
            dest=PelletState.covering,
            before=before_cover_pellet,
            conditions=can_cover_pellet,
        ),

        dict(
            trigger=release_pellet,
            source=[PelletState.loading, PelletState.monitoring, PelletState.retract],
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
                # PelletState.loading,  # not sure
                # PelletState.sending,  # not sure
                PelletState.releasing,  # could/should remove too
                # PelletState.prerelease,  # unused
                PelletState.covering,  # could/should remove too
                PelletState.monitoring,
            ),
            dest=PelletState.retract,
            before=_before_move_retract,
        ),
    ])
