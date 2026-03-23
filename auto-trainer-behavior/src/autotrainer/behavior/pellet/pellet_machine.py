import math
import os
from typing import Callable, Optional, get_type_hints, Protocol

from transitions import Machine

from autotrainer.core import EventManager, transitions_allow_functions, SystemMessageHandler, get_perf_now
from autotrainer.core import ApiEventKind as BehaviorEventKind
from autotrainer.core.multiproc import no_op_timer
from autotrainer.core.logging import get_verbose_logger

from ..intersession import IntersessionState
from .. import RecordingEndingReason
from ..behavior_algorithm import BehaviorAlgorithm, BehaviorAlgoStatus
from ..pellet_device_protocol import PelletDeviceProtocol
from ..state_machine import StateMachine, StateMachineEvents
from ..system_machine_state import SystemState

from . import PelletState

logger = get_verbose_logger(__name__)


DEFAULT_LOAD_RETRACT_COUNT_FORCE_HOME = int(os.getenv("AUTOTRAINER_LOAD_RETRACT_COUNT_FORCE_HOME", "12"))


class _load_failed_event(Protocol):

    def __call__(self, *, consecutive: int):
        """Load failed event declaration"""


class PelletMachineEvents(StateMachineEvents):

    pellet_loading: Callable[[], None]  # when a load-pellet is started executing
    pellet_sending: Callable[[], None]  # now unused
    pellet_loaded: Callable[[], None]  # when a load-pellet is finished executing AND a pellet is seen on it
    pellet_sent: Callable[[], None]  # when a send-pellet is finished executing
    load_failed: _load_failed_event


class PelletDeviceCommandFailed(RuntimeError):
    """Dedicated"""


class PelletMachine(StateMachine):

    _events_class = PelletMachineEvents

    def __init__(
        self,
        algorithm: BehaviorAlgorithm,
        msg_handler: SystemMessageHandler,
        pellet_device: PelletDeviceProtocol,
    ):
        initial_state = PelletState.home

        super().__init__(initial_state=initial_state)

        # This is primarily for unit testing.  In general, algorithm should always be passed in from the parent
        # SystemMachine.
        if algorithm is None:
            algorithm = BehaviorAlgorithm()
        self._algorithm = algorithm
        # algorithm.session_starting += self._session_started
        # algorithm.session_capture_ending += self._session_capture_ended

        self._message_handler = msg_handler
        if msg_handler is not None:
            msg_handler.ack_received += self._pellet_device_ack_received

        self._pellet_device = pellet_device

        self._consecutive_failed_load = 0
        self._load_retract_current_count = 0  # for auto-home when count >= threshold
        self._api_status_token = None
        self._api_status_token_pellet_send = None
        self._covered_state: Optional[bool] = None  # False == released ; True == covered ; None == unknown/none
        self._prev_can_cover: Optional[bool] = None
        self._prev_can_release: Optional[bool] = None
        self._prev_can_load: Optional[bool] = None
        self._prev_can_send: Optional[bool] = None
        self._prev_can_home: Optional[bool] = None
        self._prev_covered_state = None
        self._send_begin_perf_c = -math.inf
        self._send_end_perf_c = -math.inf
        self._prev_pellet_load_perf_c = -math.inf
        self._prev_notify_loaded_perf_c = -math.inf
        self._prev_notify_load_failed_perf_c = -math.inf

        self.machine = Machine(
            model=[self],
            states=list(PelletState),
            transitions=self.transitions,
            auto_transitions=False,
            initial=initial_state,
            model_override=True,
        )

        # NB: must be done AFTER creation of previous `self.machine` instance
        algorithm.relay_transitions(self)

    @property
    def events(self) -> PelletMachineEvents:
        return self._events

    @property
    def covered_state(self) -> Optional[bool]:
        """False == released, True == covered, None == unknown"""
        return self._covered_state

    # transitions

    def _before_move_home(self):
        self._api_status_token = self._pellet_device.send_home()
        if self._api_status_token is None:
            raise PelletDeviceCommandFailed
        self.post_event_content(BehaviorEventKind.pelletHomeBegin, context=self._api_status_token)

    def _before_load_pellet(self):
        logger.verbose("before_load_pellet")
        self._api_status_token = self._pellet_device.load_pellet()
        if self._api_status_token is None:
            raise PelletDeviceCommandFailed
        self.events.pellet_loading()
        self._prev_pellet_load_perf_c = get_perf_now()
        self._covered_state = None
        self.post_event_content(BehaviorEventKind.pelletLoadBegin, context=self._api_status_token)
        self._load_retract_current_count += 1

    def _before_send_pellet(self):
        # check for auto-home when load+retract counts >= threshold:
        tot_count = self._load_retract_current_count
        trigger_count = DEFAULT_LOAD_RETRACT_COUNT_FORCE_HOME
        if 0 < trigger_count <= tot_count:
            # eventual todo: use a configuration value for the threshold
            logger.notice("Forcing a send_home to reset to limits due to load + retract "
                          "count greater-or-equal than threshold: %s vs %s", self._load_retract_current_count,
                          trigger_count)
            self._pellet_device.send_home()
            self._load_retract_current_count = 0
        # apply the pellet cover or release here right before sending
        algo = self._algorithm
        # use can_cover which checks for both cover_pellet_enabled AND pellet_delivery_enabled:
        if algo.can_cover_pellet():
            if self._covered_state is not True:
                self.cover_pellet()
        elif algo.can_release_pellet():
            # maybe auto-behavior/commands are not enabled given system/app not in good mode
            if self._covered_state is not False:
                self.release_pellet()
        token = self._pellet_device.send_pellet()
        if token is None:
            raise PelletDeviceCommandFailed
        self._api_status_token_pellet_send = self._api_status_token = token
        self._send_begin_perf_c = get_perf_now()
        self.events.pellet_sending()
        self.post_event_content(BehaviorEventKind.pelletSendBegin, context=token)

    def _before_cover_pellet(self):
        self._api_status_token = self._pellet_device.cover_pellet()
        if self._api_status_token is None:
            raise PelletDeviceCommandFailed
        self._covered_state = True
        self.post_event_content(BehaviorEventKind.pelletCoverBegin, context=self._api_status_token)

    def _before_release_pellet(self):
        self._api_status_token = self._pellet_device.release_pellet()
        if self._api_status_token is None:
            raise PelletDeviceCommandFailed
        self._covered_state = False
        self.post_event_content(BehaviorEventKind.pelletReleaseBegin, context=self._api_status_token)

    def can_move_home(self):
        can = self.can_use_pellet_command()
        if can != self._prev_can_home:
            self._prev_can_home = can
            self.post_event_content(BehaviorEventKind.pelletHomeCan, context=can)
        return can

    def can_load_pellet(self):
        can_use = self.can_use_pellet_command()
        algo_would_load = self._algorithm.would_load_pellet(pellet_state=self._state)
        if can_use and algo_would_load:
            self._check_pellet_load_failed()
        can = can_use and self._algorithm.can_load_pellet(pellet_state=self._state)
        if can != self._prev_can_load:
            self._prev_can_load = can
            self.post_event_content(BehaviorEventKind.pelletLoadCan, context=can)
        return can

    def can_send_pellet(self):
        can = self.can_use_pellet_command() and self._algorithm.can_send_pellet()
        if can != self._prev_can_send:
            self._prev_can_send = can
            self.post_event_content(BehaviorEventKind.pelletSendCan, context=can)
        return can

    def can_cover_pellet(self):
        can = self.can_use_pellet_command() and self._algorithm.can_cover_pellet()
        if can != self._prev_can_cover:
            self._prev_can_cover = can
            self.post_event_content(BehaviorEventKind.pelletCoverCan, context=can)
        return can

    def can_release_pellet(self):
        can = self.can_use_pellet_command() and self._algorithm.can_release_pellet()
        if can != self._prev_can_release:
            self._prev_can_release = can
            self.post_event_content(BehaviorEventKind.pelletReleaseCan, context=can)
        return can

    def can_use_pellet_command(self):
        return self._api_status_token is None

    def pellet_seen(self, seen: bool):
        self.environment_changed(seen, caller="pellet_seen", is_from_inference=True)

    # region Callbacks

    def _before_move_retract(self):
        if self._algorithm.pellet_cover_enabled:
            if self._covered_state is not True:
                self.cover_pellet()
                self._api_status_token = None
        self._api_status_token = self._pellet_device.send_retract()
        if self._api_status_token is None:
            raise PelletDeviceCommandFailed
        self._load_retract_current_count += 1

    @BehaviorAlgorithm.relay_func(wait=False)
    def _pellet_device_ack_received(self, token: Optional[str]):
        if token is None:
            return

        logger.debug("pellet_ack_received: %s", token)
        if self._api_status_token is None:
            # External command. Safe to ignore.
            return

        if token != self._api_status_token:
            # External command while we are waiting for our own.  Track in case it is causing conflicts.
            self.post_event_content(BehaviorEventKind.pelletExternalToken, context=token)
            logger.debug("ignoring pellet delivery token from external command. token=%r api_status=%r",
                         token, self._api_status_token)
            return

        self.post_event_content(BehaviorEventKind.pelletAcknowledgeToken, context=token)

        self._api_status_token = None
        perf_now = get_perf_now()
        if token == self._api_status_token_pellet_send:
            self._send_end_perf_c = perf_now
            self._api_status_token_pellet_send = None
            self.events.pellet_sent()

        # nb: in live we could bypass this call : it's anyway called with live-inference pellet-seen callback..
        self.environment_changed(
            # we might want to use:
            pellet_seen=self._algorithm.pellet_recently_seen,
            # so that pellet_seen is more accurately handled:
            # i.e: if this device-ack is/was for a load-pellet, and that the pellet missed to load,
            # we could possibly & erroneously acknowledge a successfully load-pellet...
            caller="pellet_device_ack_received",
        )

    def get_pellet_send_begin_age(self, perf_now: float):
        return perf_now - self._send_begin_perf_c

    def get_pellet_send_end_age(self, perf_now: float):
        return perf_now - self._send_end_perf_c

    # endregion

    def _notify_pellet_loaded_ok(self):
        # always check:
        if self._prev_notify_loaded_perf_c < self._prev_pellet_load_perf_c:
            self._prev_notify_loaded_perf_c = get_perf_now()
            logger.info("Notifying pellet loaded successfully")
            self._consecutive_failed_load = 0
            self.events.pellet_loaded()

    def _check_pellet_load_failed(self):
        if (
            self._prev_notify_loaded_perf_c < self._prev_pellet_load_perf_c
            and self._prev_notify_load_failed_perf_c < self._prev_pellet_load_perf_c
        ):
            self._consecutive_failed_load += 1
            self._prev_notify_load_failed_perf_c = get_perf_now()
            logger.info("Notifying pellet load failed, consecutive=%s", self._consecutive_failed_load)
            self.events.load_failed(consecutive=self._consecutive_failed_load)

    @BehaviorAlgorithm.relay_func
    def environment_changed(
        self,
        pellet_seen: bool = True,
        must_release: bool = False,
        *,
        caller: str = "not-provided",
        is_from_inference: bool = False,
    ):
        # always use the thread lock, given this can be called from different threads at the same time,
        # so possibly completely intermixed/leaved, which we want to protect from, so:
        with self._algorithm.thread_lock:
            self.__try_next_state(pellet_seen, must_release,
                                  caller=caller, is_from_inference=is_from_inference)

    def __try_next_state(
        self,
        pellet_seen: bool = True,
        must_release: bool = False,
        *,
        caller: str,
        is_from_inference: bool = False,
    ):
        algo = self._algorithm
        reason: str = "unknown"
        retrying = False

        def logit():
            if retrying:
                func = logger.spam if reason != "release_when_sent_cover_enabled" else logger.debug
            else:
                func = logger.verbose
            func(
                "try_next_state cur=%s from %s: %s -> from_inference=%s in_session=%s pellet_seen=%s recently=%s triangle_recently_seen=%s "
                "session_mouse_seen=%s session_pellet_count=%s must_release=%s "
                "algo_system_state=%s intersession_state=%s "
                "pellet_seen_age=%.1fsec covered_state=%s",
                cur_state, caller, reason, is_from_inference,
                algo.is_in_session, pellet_seen,
                algo.pellet_recently_seen, algo.triangle_recently_seen,
                algo.session_mouse_seen, algo.session_pellet_loaded_count, must_release,
                algo.system_state, algo.intersession_state,
                algo.pellet_seen_age, self._covered_state,
            )

        def log_could_retry_shortly():
            # retry shortly currently disabled.
            nonlocal reason, retrying
            retrying = True
            reason = f"would have retried shortly {reason}"
            logit()

        if algo.algo_paused:  # really unsure we should keep,
            # we may want to handle the user commands still when algo-paused (emergency)
            return

        cur_state = self._state

        if algo.system_state == SystemState.intersession:
            if algo.intersession_state == IntersessionState.segmentation:
                # waiting inference is back, nothing we can do
                return

        if cur_state in {PelletState.loading, PelletState.retract}:
            if not self.can_use_pellet_command():
                # always wait the previous movement is finished
                return
            # this is going to be called at end of intersession after going to detection phase,
            # basically when inference is back to live
            if self.can_load_pellet():
                reason = "load_pellet_when_not_seen_and_retract_or_loading"
                logit()
                self.load_pellet()
            else:
                # either pellet is seen, or we don't know (might be not visible on cameras),
                if cur_state == PelletState.loading and pellet_seen and is_from_inference:
                    # TODO: using only 1 inference result to notify pellet loaded is risky in case of false positive
                    # could/should use instead of more reliable way,
                    # as waiting to have at least more than only 1 inference result..
                    self._notify_pellet_loaded_ok()
                # current state is either retract or loading (loaded),
                # even if pellet is not seen, send it to deliver,
                # the end position of load-pellet sequence might not be (entirely or on all units) visible by camera,
                if algo.can_send_pellet():
                    reason = "send_pellet_when_loaded_or_retract"
                    logit()
                    self.send_pellet()

        elif cur_state == PelletState.sending:
            reason = "monitor_when_sent"
            logit()
            self.monitor_pellet()
            self.__try_next_state(pellet_seen, must_release, caller=caller, is_from_inference=is_from_inference)

        elif cur_state in {PelletState.covering, PelletState.releasing}:
            if self.can_send_pellet():
                reason = "send_pellet_when_covered_or_released"
                logit()
                self.send_pellet()
            # NB: this is remains mainly for manual command.
            # In the normal algo-active & animal-in-training case,
            # the cover/release is already automatically done/included with the send_pellet trigger/command,
            # right before send_pellet is actually executed.
            # So in the non- algo-active & animal-in-training case, and if cover/release is executed with user command,
            # then the state will remains after, until another command/trigger/state-change is executed.

        elif cur_state == PelletState.home:
            reason = "send_pellet_when_home"
            if self.can_send_pellet():
                logit()
                self.send_pellet()
                self.monitor_pellet()
                self.__try_next_state(pellet_seen, must_release, caller=caller, is_from_inference=is_from_inference)
            else:
                log_could_retry_shortly()

        elif cur_state == PelletState.monitoring:

            # previous load-pellet could have missed to notify for pellet-loaded event,
            # if/when pellet is not visible at end of load-pellet sequence. So have to recheck here:
            if pellet_seen and is_from_inference:
                self._notify_pellet_loaded_ok()

            if self.can_load_pellet():
                reason = "load_pellet_when_monitoring_can_load_pellet"
                logit()
                self.load_pellet()
                return

            if self._prev_covered_state is not self._covered_state:
                logger.debug("covered_state: %s -> %s", self._prev_covered_state, self._covered_state)
                self._prev_covered_state = self._covered_state

            # NB: also having to use algo.can_cover_pellet(),
            # given algo.can_release_pellet()/both depends on conditions
            can_cover = algo.can_cover_pellet()
            can_release = algo.can_release_pellet()

            release_or_cover_action = None
            if can_release:
                # nb: keep this second inner if not grouped/and'ed with the previous one,
                # otherwise cover will continuously switch between covered and released.
                if self._covered_state is not False:
                    reason = "release_pellet_in_monitoring"
                    release_or_cover_action = self.release_pellet

            elif can_cover:
                if self._covered_state is not True:  # noqa
                    reason = "cover_pellet_in_monitoring"
                    release_or_cover_action = self.cover_pellet

            if release_or_cover_action is not None:
                if self.can_use_pellet_command():
                    logit()
                    release_or_cover_action()
                    self._api_status_token = None  # no need wait for ack
                    self.monitor_pellet()
                else:
                    log_could_retry_shortly()

        else:
            logger.warning("unknown state: %s", cur_state)

    # region State Machine Requirements
    # Methods required for model_override=True to work.

    # NB: keeping to not have warning from Machine transition parent class
    def trigger(self):
        """"""

    def may_trigger(self):
        """"""

    def move_home(self):
        """Move home"""

    def may_move_home(self):
        """May move home"""

    def move_retract(self):
        """Trigger a "move" to retract position (y - 10 relative)"""

    def may_move_retract(self):
        """May move retract"""

    def load_pellet(self):
        """Load pellet"""

    def may_load_pellet(self):
        """May load pellet"""

    def force_load_pellet(self):
        """Same than load but does not require can_load_pellet condition"""

    def may_force_load_pellet(self):
        """May force load pellet"""

    def send_pellet(self):
        """Send pellet to deliver position"""

    def force_send_pellet(self):
        """Force a send pellet to deliver position"""

    def may_send_pellet(self):
        """May Send pellet to deliver position"""

    def may_force_send_pellet(self):
        """May Force Send pellet to deliver position"""

    def release_pellet(self):
        """Release pellet cover"""

    def force_release_pellet(self):
        """Force release pellet"""

    def may_force_release_pellet(self):
        """May Force Release pellet to deliver position"""

    def may_release_pellet(self):
        """May Release pellet cover"""

    def cover_pellet(self):
        """Cover pellet cover"""

    def force_cover_pellet(self):
        """Force cover pellet"""

    def may_cover_pellet(self):
        """May Cover pellet cover"""

    def may_force_cover_pellet(self):
        """May Force Cover pellet to deliver position"""

    def monitor_pellet(self):
        """Monitor pellet"""

    def may_monitor_pellet(self):
        """May Monitor pellet"""

    def is_home(self):
        """is home"""

    def is_loading(self):
        """is loading"""

    def is_sending(self):
        """is sending"""

    def is_covering(self):
        """is covering"""

    def is_releasing(self):
        """is releasing"""

    def is_monitoring(self):
        """is monitoring"""

    def is_retract(self):
        """is retract"""

    # endregion

    # Note that transitions have conditions, where applicable.  What may appear to be unconditional calls to cover,
    # release, or otherwise perform pellet transitions will not succeed and perform those actions if these conditions
    # are met.
    transitions = transitions_allow_functions([
        dict(
            trigger=load_pellet,
            source=[PelletState.loading, PelletState.monitoring, PelletState.covering, PelletState.retract],
            dest=PelletState.loading,
            before=_before_load_pellet,
            conditions=can_load_pellet,
        ),

        dict(
            trigger=force_load_pellet,
            source="*",
            dest=PelletState.loading,
            before=_before_load_pellet,
            # conditions=can_load_pellet,  # contrary to load_pellet
        ),

        dict(
            trigger=send_pellet,
            source="*",
            dest=PelletState.sending,
            before=_before_send_pellet,
            conditions=can_send_pellet,
        ),

        dict(
            trigger=force_send_pellet,
            source="*",
            dest=PelletState.sending,
            before=_before_send_pellet,
            # conditions=can_send_pellet,  # contrary to send_pellet
        ),

        dict(
            trigger=cover_pellet,
            source="*",
            dest=PelletState.covering,
            before=_before_cover_pellet,
            conditions=can_cover_pellet,
        ),

        dict(
            trigger=force_cover_pellet,
            source="*",
            dest=PelletState.covering,
            before=_before_cover_pellet,
            # conditions=can_cover_pellet,
        ),

        dict(
            trigger=release_pellet,
            source="*",
            dest=PelletState.releasing,
            before=_before_release_pellet,
            conditions=can_release_pellet,
        ),

        dict(
            trigger=force_release_pellet,
            source="*",
            dest=PelletState.releasing,
            before=_before_release_pellet,
            # conditions=can_release_pellet,
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
            before=_before_move_home,
            conditions=can_move_home,
        ),

        dict(
            trigger=move_retract,
            source=(
                # possible todo: don't see why we could not allow it from all states ("*")
                # is only executed when going into intersession if/when pellet still present
                PelletState.monitoring,
            ),
            dest=PelletState.retract,
            before=_before_move_retract,
        ),
    ])
