import logging
import time
from enum import Enum

from events import Events
from transitions import Machine

from autotrainer.core.logging import get_verbose_logger
from autotrainer.core import EventManager, MessageHandler, ObservableObject

from ..behavior_algorithm import BehaviorAlgorithm
from ..behavior_event_kind import BehaviorEventKind
from ..pellet_device_protocol import PelletDeviceProtocol
from ..state_machine import StateMachine
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


class PelletMachine(StateMachine):

    # Note that transitions have conditions, where applicable.  What may appear to be unconditional calls to cover,
    # release, or otherwise perform pellet transitions will not succeed and perform those actions if these conditions
    # are met.
    transitions = [
        {"trigger": "load_pellet", "source": [PelletState.monitoring, PelletState.covering],
         "dest": PelletState.loading, "before": "before_load_pellet", "after": "after_load_pellet",
         "conditions": "can_load_pellet"},
        {"trigger": "send_pellet", "source": [PelletState.loading, PelletState.home, PelletState.prerelease],
         "dest": PelletState.sending, "before": "before_send_pellet", "conditions": "can_send_pellet"},
        {"trigger": "prerelease_pellet", "source": [PelletState.loading, PelletState.home],
         "dest": PelletState.prerelease, "before": "before_prerelease_pellet", "conditions": "can_prerelease_pellet"},
        {"trigger": "cover_pellet", "source": PelletState.monitoring, "dest": PelletState.covering,
         "before": "before_cover_pellet", "conditions": "can_cover_pellet"},
        {"trigger": "release_pellet", "source": [PelletState.covering, PelletState.monitoring],
         "dest": PelletState.releasing, "before": "before_release_pellet",
         "conditions": "can_release_pellet"},
        {"trigger": "monitor_pellet", "source": "*", "dest": PelletState.monitoring},
        {"trigger": "move_home", "source": "*", "dest": PelletState.home, "before": "before_move_home",
         "conditions": "can_move_home"},
        dict(
            trigger="move_retract",
            source=(PelletState.sending, PelletState.releasing, PelletState.covering, PelletState.monitoring),
            dest=PelletState.retract,
            after="_move_retract",
        ),
    ]

    def __init__(self, algorithm: BehaviorAlgorithm = None, msg_handler: MessageHandler = None,
                 pellet_device: PelletDeviceProtocol = None):

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
        self._log_next_try_next_state = time.perf_counter() + 15

        self.machine = Machine(model=[self], states=list(PelletState),
                               transitions=PelletMachine.transitions, auto_transitions=False,
                               initial=initial_state, model_override=True,
                       )

    @property
    def algorithm(self):
        return self._algorithm

    @property
    def events(self):
        return self._events

    def environment_changed(self):
        self._try_next_state()

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

    def can_send_pellet(self, _prev_val=[False]):
        can = self.can_use_pellet_command()
        if __debug__:
            prev = _prev_val[0]
            if can != prev:
                logger.debug("can_send_pellet: can=%s state=%s token=%s",
                             can, self._state, self._api_status_token)
            _prev_val[0] = can
        EventManager.default().post_event_content(BehaviorEventKind.pelletSendCan, context=can)
        return can

    def can_cover_pellet(self):
        can = self.can_use_pellet_command() and self._algorithm.can_cover_pellet()
        EventManager.default().post_event_content(BehaviorEventKind.pelletCoverCan, context=can)
        return can

    def can_prerelease_pellet(self):
        can = self.can_use_pellet_command() and self._algorithm.can_release_pellet()
        EventManager.default().post_event_content(BehaviorEventKind.pelletPrereleaseCan, context=can)
        return can

    def can_release_pellet(self):
        can = self.can_use_pellet_command() and self._algorithm.can_release_pellet()
        EventManager.default().post_event_content(BehaviorEventKind.pelletReleaseCan, context=can)
        return can

    def can_use_pellet_command(self):
        return self._api_status_token is None

    def pellet_seen(self, seen: bool):
        self._try_next_state(seen)

    # region Callbacks
    def _session_starting(self):
        # Strictly speaking, the pellet should not be covered here when covering is disabled.  Under that condition,
        # must release could be set to False.  However, given how critical it is that the pellet is not covered when
        # disabled, go ahead and request a release under all conditions, even though it should be a no-op in that
        # instance.
        self._try_next_state(True, True)

    def _session_ending(self):
        self._try_next_state()

    def _move_retract(self):
        self._pellet_device.send_retract()

    def _pellet_device_ack_received(self, token: str):
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

        self._try_next_state()

    # endregion

    def _try_next_state(self, pellet_seen: bool = True, must_release: bool = False):
        def logit():
            t_perf_now = time.perf_counter()
            if self._log_next_try_next_state >= t_perf_now:
                logger.debug("try_next_state: pellet_seen=%s must_release=%s pellet_state=%s algo_system_state=%s",
                             pellet_seen, must_release, self._state, self.algorithm.system_state)
                # self._log_next_try_next_state = t_perf_now + 1

        # Always arrest to the home position during intersession.
        if self.algorithm.system_state == SystemState.intersession:
            if self.state != PelletState.retract:
                __debug__ and logit()
                self.move_retract()
            return

        if self.state == PelletState.loading:
            __debug__ and logit()
            if self.algorithm.pellet_cover_enabled:
                self.send_pellet()
            else:
                self.prerelease_pellet()
        elif self.state == PelletState.prerelease:
            __debug__ and logit()
            self.send_pellet()
        elif self.state == PelletState.sending:
            __debug__ and logit()
            if self.algorithm.pellet_cover_enabled:
                # The hardware ends the send phase with the pellet covered.  Put things in a consistent state of
                # covered without sending an unnecessary command.
                self.state = PelletState.covering
                self.release_pellet()
            else:
                self.monitor_pellet()
        elif self.state == PelletState.covering:
            __debug__ and logit()
            if not pellet_seen:
                self.load_pellet()
            else:
                self.release_pellet()
        elif self.state == PelletState.releasing:
            self.monitor_pellet()
        elif self.state == PelletState.home:
            self.send_pellet()
        elif self.state == PelletState.monitoring:
            if self._algorithm.is_in_session:
                if must_release:
                    __debug__ and logit()
                    self.release_pellet()
                elif not pellet_seen:
                    __debug__ and logit()
                    self.load_pellet()
            else:
                __debug__ and logit()
                if not pellet_seen:
                    self.load_pellet()
                else:
                    self.cover_pellet()

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
