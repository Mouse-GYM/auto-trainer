import math
import os
from typing import Callable, Optional, get_type_hints, Protocol

from transitions import Machine

from autotrainer.api import ApiEventKind

from autotrainer.core import transitions_allow_functions, SystemMessageHandler, get_perf_now
from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.pose_elements import SceneElement

from ..intersession import IntersessionState
from ..behavior_algorithm import BehaviorAlgorithm
from ..pellet_device_protocol import PelletDeviceProtocol
from ..state_machine import StateMachine, StateMachineEvents
from ..system_machine_state import SystemState

from . import PelletState

logger = get_verbose_logger(__name__)


DEFAULT_LOAD_RETRACT_COUNT_FORCE_HOME = int(os.getenv("AUTOTRAINER_LOAD_RETRACT_COUNT_FORCE_HOME", "12"))


class _pellet_load_failed_event(Protocol):

    def __call__(self, *, consecutive: int):
        """Load failed event declaration"""


class PelletMachineEvents(StateMachineEvents):

    pellet_loading: Callable[[], None]  # when a load-pellet is started executing
    pellet_sending: Callable[[], None]  # now unused
    pellet_loaded: Callable[[], None]  # when a load-pellet is finished executing AND a pellet is seen on it
    pellet_sent: Callable[[], None]  # when a send-pellet is finished executing
    pellet_load_failed: _pellet_load_failed_event


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
        self._token_pellet_send = None
        self._token_pellet_load = None
        self._token_move_retract = None
        self._token_cover_pellet = None
        self._token_release_pellet = None
        self._token_move_home = None

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
        algorithm.relay_transitions(self, wait=False)

    @property
    def events(self) -> PelletMachineEvents:
        return self._events

    @property
    def covered_state(self) -> Optional[bool]:
        """False == released, True == covered, None == unknown"""
        return self._covered_state

    # transitions

    def _before_move_home(self, *, force: bool=False):
        token = self._pellet_device.send_home()
        if token is None:
            raise PelletDeviceCommandFailed
        self._api_status_token = self._token_move_home = token
        self.post_event_content(ApiEventKind.pelletHomeBegin, data=dict(context=token))

    def _before_load_pellet(self, *, force: bool=False, use_any_cam: bool=False):
        del force, use_any_cam  # only used for condition can_load_pellet
        logger.verbose("before_load_pellet")
        token = self._pellet_device.load_pellet()
        if token is None:
            raise PelletDeviceCommandFailed
        self._api_status_token = self._token_pellet_load = token
        self.events.pellet_loading()
        self._prev_pellet_load_perf_c = get_perf_now()
        self._covered_state = None
        self.post_event_content(ApiEventKind.pelletLoadBegin, data=dict(context=token))
        self._load_retract_current_count += 1

    def _before_send_pellet(self, *, force: bool=False):
        # check for auto-home when load+retract counts >= threshold:
        tot_count = self._load_retract_current_count
        trigger_count = DEFAULT_LOAD_RETRACT_COUNT_FORCE_HOME
        if 0 < trigger_count <= tot_count:
            # eventual todo: use a configuration value for the threshold
            logger.notice("Forcing a send_home to reset to limits due to load + retract "
                          "count greater-or-equal than threshold: %s vs %s", self._load_retract_current_count,
                          trigger_count)
            self._event_manager.post_event_content(ApiEventKind.pelletHomeReset, data=dict(cycles=tot_count))
            self._pellet_device.send_home()
            self._load_retract_current_count = 0

        # apply the pellet cover or release here right before sending
        algo = self._algorithm
        # use can_cover which checks for both cover_pellet_enabled AND pellet_delivery_enabled:
        if algo.can_cover_pellet():
            if self._covered_state is not True:
                with BehaviorAlgorithm.set_allow_reentrant(True):
                    self.cover_pellet()
        elif algo.can_release_pellet():
            # maybe auto-behavior/commands are not enabled given system/app not in good mode
            if self._covered_state is not False:
                with BehaviorAlgorithm.set_allow_reentrant(True):
                    self.release_pellet()
        token = self._pellet_device.send_pellet()
        if token is None:
            raise PelletDeviceCommandFailed
        self._token_pellet_send = self._api_status_token = token
        self._send_begin_perf_c = get_perf_now()
        self.events.pellet_sending()
        self.post_event_content(ApiEventKind.pelletSendBegin, data=dict(context=token))

    def _before_cover_pellet(self, *, force: bool=False):
        token = self._pellet_device.cover_pellet()
        if token is None:
            raise PelletDeviceCommandFailed
        self._api_status_token = self._token_cover_pellet = token
        self._covered_state = True
        self.post_event_content(ApiEventKind.pelletCoverBegin, data=dict(context=token))

    def _before_release_pellet(self, *, force: bool=False):
        token = self._pellet_device.release_pellet()
        if token is None:
            raise PelletDeviceCommandFailed
        self._api_status_token = self._token_release_pellet = token
        self._covered_state = False
        self.post_event_content(ApiEventKind.pelletReleaseBegin, data=dict(context=token))

    def can_move_home(self, *, force: bool=False):
        can = force or self.can_use_pellet_command()
        if can != self._prev_can_home:
            self._prev_can_home = can
        return can

    def can_load_pellet(self, *, force: bool=False, use_any_cam: bool = False):
        """Is more: *should* or *has to* load pellet"""
        can_use = self.can_use_pellet_command()
        # perf_now = get_perf_now()
        # algo_would_load = self._algorithm.would_load_pellet(
        #     pellet_state=self._state, use_any_cam=use_any_cam, perf_now=perf_now)
        can = force or (
            can_use
            and self._algorithm.can_load_pellet(pellet_state=self._state, use_any_cam=use_any_cam)
        )
        if can != self._prev_can_load:
            self._prev_can_load = can
        return can

    def can_send_pellet(self, *, force: bool=False):
        can = force or (
            self.can_use_pellet_command() and self._algorithm.can_send_pellet()
        )
        if can != self._prev_can_send:
            self._prev_can_send = can
        return can

    def can_cover_pellet(self, *, force: bool=False):
        can = force or (
            self.can_use_pellet_command()
            and self._algorithm.can_cover_pellet()
        )
        if can != self._prev_can_cover:
            self._prev_can_cover = can
        return can

    def can_release_pellet(self, *, force: bool=False):
        can = force or (
            self.can_use_pellet_command()
            and self._algorithm.can_release_pellet()
        )
        if can != self._prev_can_release:
            self._prev_can_release = can
        return can

    def can_use_pellet_command(self):
        return self._api_status_token is None

    def pellet_seen(self, seen: bool):
        self.environment_changed(seen, caller="pellet_seen", is_from_inference=True)

    # region Callbacks

    def _before_move_retract(self):
        if self._algorithm.pellet_cover_enabled:
            if self._covered_state is not True:
                with BehaviorAlgorithm.set_allow_reentrant(True):
                    self.cover_pellet()
                self._api_status_token = None
        token = self._pellet_device.send_retract()
        if token is None:
            raise PelletDeviceCommandFailed
        self._api_status_token = self._token_move_retract = token
        self.post_event_content(ApiEventKind.pelletRetractBegin, data=dict(context=token))
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
            # self.post_event_content(ApiEventKind.pelletExternalToken, context=token)
            logger.debug("ignoring pellet delivery token from external command. token=%r api_status=%r",
                         token, self._api_status_token)
            return

        self._api_status_token = None
        perf_now = get_perf_now()
        api_evt = None
        if token == self._token_pellet_send:
            self._send_end_perf_c = perf_now
            self._token_pellet_send = None
            api_evt = ApiEventKind.pelletSendEnd
            self.events.pellet_sent()

        elif token == self._token_pellet_load:
            self._token_pellet_load = None
            api_evt = ApiEventKind.pelletLoadEnd

        elif token == self._token_cover_pellet:
            self._token_cover_pellet = None
            api_evt = ApiEventKind.pelletCoverEnd

        elif token == self._token_release_pellet:
            self._token_release_pellet = None
            api_evt = ApiEventKind.pelletReleaseEnd

        elif token == self._token_move_retract:
            self._token_move_retract = None
            api_evt = ApiEventKind.pelletRetractEnd

        elif token == self._token_move_home:
            self._token_move_home = None
            api_evt = ApiEventKind.pelletHomeEnd

        if api_evt is not None:
            self.post_event_content(api_evt, data=dict(context=token))

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

    def _check_notify_pellet_loaded_ok(self, *, perf_now):
        algo = self._algorithm
        all_cams_ctx = algo.all_cams_scene_parts_presence_context
        recently_seen = all_cams_ctx.get_recently_seen(SceneElement.Pellet, algo.pellet_missing_time,
                                                       perf_now=perf_now)

        if recently_seen and self._prev_notify_loaded_perf_c < self._prev_pellet_load_perf_c:
            self._prev_notify_loaded_perf_c = perf_now
            logger.info("Notifying pellet loaded successfully")
            self._consecutive_failed_load = 0
            self.events.pellet_loaded()

    def _check_notify_pellet_load_failed(self, *, perf_now):
        if (
            self._prev_notify_loaded_perf_c < self._prev_pellet_load_perf_c
            and self._prev_notify_load_failed_perf_c < self._prev_pellet_load_perf_c
        ):
            self._consecutive_failed_load += 1
            self._prev_notify_load_failed_perf_c = perf_now
            logger.info("Notifying pellet load failed, consecutive=%s", self._consecutive_failed_load)
            self.events.pellet_load_failed(consecutive=self._consecutive_failed_load)

    @BehaviorAlgorithm.relay_func(wait=False)
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
        # NB: pellet_seen is on any cam

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
                algo.system_state, algo.intersession_state, algo.pellet_presence_age, self._covered_state,
            )

        def log_could_retry_shortly():
            # retry shortly currently disabled.
            nonlocal reason, retrying
            retrying = True
            reason = f"would have retried shortly {reason}"
            logit()

        perf_now = get_perf_now()
        cur_state = self._state
        can_use_command = self.can_use_pellet_command()
        all_cams_ctx = algo.all_cams_scene_parts_presence_context
        any_cams_ctx = algo.any_cams_scene_parts_presence_context
        pellet_seen_all = all_cams_ctx.get_part_seen(SceneElement.Pellet)
        triangle_seen_all = all_cams_ctx.get_part_seen(SceneElement.Triangle)
        pellet_seen_any = any_cams_ctx.get_part_seen(SceneElement.Pellet)

        if can_use_command:  # wait no move in progress
            if pellet_seen_all:
                self._check_notify_pellet_loaded_ok(perf_now=perf_now)
            elif not pellet_seen and cur_state == PelletState.loading:
                if triangle_seen_all and not pellet_seen_any:
                    self._check_notify_pellet_load_failed(perf_now=perf_now)

        if algo.algo_paused:  # really unsure we should keep,
            # we may want to handle the user commands still when algo-paused (emergency)
            return

        if algo.system_state == SystemState.intersession:
            if algo.intersession_state == IntersessionState.segmentation:
                # waiting inference is back, nothing we can do
                return

        if cur_state in {PelletState.loading, PelletState.retract}:
            if not can_use_command:
                # always wait the previous movement is finished
                return
            # this is going to be called at end of intersession after going to detection phase,
            # basically when inference is back to live
            if self.can_load_pellet(use_any_cam=True):
                reason = "load_pellet_when_not_seen_and_retract_or_loading"
                logit()
                with BehaviorAlgorithm.set_allow_reentrant(True):
                    self.load_pellet(use_any_cam=True)
            else:
                # current state is either retract or loading (loaded),
                # even if pellet is not seen, send it to deliver,
                # the end position of load-pellet sequence might not be (entirely or on all units) visible by camera,
                if algo.can_send_pellet():
                    reason = "send_pellet_when_loaded_or_retract"
                    logit()
                    with BehaviorAlgorithm.set_allow_reentrant(True):
                        self.send_pellet()

        elif cur_state == PelletState.sending:
            if can_use_command:
                reason = "monitor_when_sent"
                logit()
                with BehaviorAlgorithm.set_allow_reentrant(True):
                    self.monitor_pellet()
                    self.environment_changed(pellet_seen, must_release,
                                             caller=caller, is_from_inference=is_from_inference)

        elif cur_state in {PelletState.covering, PelletState.releasing}:
            if self.can_send_pellet():
                reason = "send_pellet_when_covered_or_released"
                logit()
                with BehaviorAlgorithm.set_allow_reentrant(True):
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
                with BehaviorAlgorithm.set_allow_reentrant(True):
                    self.send_pellet()
            else:
                log_could_retry_shortly()

        elif cur_state == PelletState.monitoring:

            if self.can_load_pellet():
                reason = "load_pellet_when_monitoring_can_load_pellet"
                logit()
                with BehaviorAlgorithm.set_allow_reentrant(True):
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
                if can_use_command:
                    logit()
                    with BehaviorAlgorithm.set_allow_reentrant(True):
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

    def move_home(self, *, force: bool=False):
        """Move home"""

    def may_move_home(self):
        """May move home"""

    def move_retract(self):
        """Trigger a "move" to retract position (y - 10 relative)"""

    def may_move_retract(self):
        """May move retract"""

    def load_pellet(self, *, force: bool=False, use_any_cam: bool=False):
        """Load pellet"""

    def may_load_pellet(self, *, force: bool=False, use_any_cam: bool=False):
        """May load pellet"""

    def send_pellet(self, *, force: bool=False):
        """Send pellet to deliver position"""

    def may_send_pellet(self):
        """May Send pellet to deliver position"""

    def release_pellet(self, *, force: bool = False):
        """Release pellet cover"""

    def may_release_pellet(self):
        """May Release pellet cover"""

    def cover_pellet(self, *, force: bool=False):
        """Cover pellet cover"""

    def may_cover_pellet(self):
        """May Cover pellet cover"""

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
            source="*",
            dest=PelletState.loading,
            before=_before_load_pellet,
            conditions=can_load_pellet,
        ),

        dict(
            trigger=send_pellet,
            source="*",
            dest=PelletState.sending,
            before=_before_send_pellet,
            conditions=can_send_pellet,
        ),

        dict(
            trigger=cover_pellet,
            source="*",
            dest=PelletState.covering,
            before=_before_cover_pellet,
            conditions=can_cover_pellet,
        ),

        dict(
            trigger=release_pellet,
            source="*",
            dest=PelletState.releasing,
            before=_before_release_pellet,
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
