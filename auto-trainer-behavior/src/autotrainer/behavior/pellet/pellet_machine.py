import logging
from enum import Enum

from events import Events
from transitions import Machine

from autotrainer.core import EventManager, MessageHandler

from ..behavior_algorithm import BehaviorAlgorithm
from ..behavior_event_kind import BehaviorEventKind
from ..pellet_device_protocol import PelletDeviceProtocol
from ..system_machine_state import SystemState

logger = logging.getLogger(__name__)


class PelletState(str, Enum):
    monitoring = "monitoring",
    loading = "loading",
    prerelease = "prerelease",
    sending = "sending",
    releasing = "releasing"
    covering = "covering",
    home = "home"


class PelletMachine:
    states = [e for e in PelletState]

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
         "conditions": "can_move_home"}
    ]

    def __init__(self, algorithm: BehaviorAlgorithm = None, msg_handler: MessageHandler = None,
                 pellet_device: PelletDeviceProtocol = None):
        self.state = PelletState.covering

        self.machine = Machine(model=self, states=PelletMachine.states,
                               transitions=PelletMachine.transitions, auto_transitions=False,
                               initial=PelletState.monitoring, model_override=True)

        # This is primarily for unit testing.  In general, algorithm should always be passed in from the parent
        # SystemMachine.
        self._algorithm = algorithm if algorithm is not None else BehaviorAlgorithm()

        self._algorithm.session_starting += self._session_starting
        self._algorithm.session_ending += self._session_ending

        self._message_handler = msg_handler

        if self._message_handler is not None:
            self._message_handler.ack_received += self._pellet_device_ack_received

        self._pellet_device = pellet_device

        self._api_status_token = None

        self._events = Events(("pellet_loading", "pellet_sending"))

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
            EventManager.post_event(BehaviorEventKind.pelletHomeBegin, context=self._api_status_token)
        else:
            self._api_status_token = None

    def before_load_pellet(self):
        if self._pellet_device is not None:
            self.events.pellet_loading()
            self._api_status_token = self._pellet_device.load_pellet()
            EventManager.post_event(BehaviorEventKind.pelletLoadBegin, context=self._api_status_token)
        else:
            self._api_status_token = None

    def before_send_pellet(self):
        if self._pellet_device is not None:
            self.events.pellet_sending()
            self._api_status_token = self._pellet_device.send_pellet()
            EventManager.post_event(BehaviorEventKind.pelletSendBegin, context=self._api_status_token)
        else:
            self._api_status_token = None

    def before_prerelease_pellet(self):
        if self._pellet_device is not None:
            self._api_status_token = self._pellet_device.release_pellet()
            EventManager.post_event(BehaviorEventKind.pelletPrereleaseBegin, context=self._api_status_token)
        else:
            self._api_status_token = None

    def after_load_pellet(self):
        self._algorithm.pellet_loaded()

    def before_cover_pellet(self):
        if self._pellet_device is not None:
            self._api_status_token = self._pellet_device.cover_pellet()
            EventManager.post_event(BehaviorEventKind.pelletCoverBegin, context=self._api_status_token)
        else:
            self._api_status_token = None

    def before_release_pellet(self):
        if self._pellet_device is not None:
            self._api_status_token = self._pellet_device.release_pellet()
            EventManager.post_event(BehaviorEventKind.pelletReleaseBegin, context=self._api_status_token)
        else:
            self._api_status_token = None

    def can_move_home(self):
        can = self.can_use_pellet_command()
        EventManager.post_event(BehaviorEventKind.pelletHomeCan, context=can)
        return can

    def can_load_pellet(self):
        can = self.can_use_pellet_command() and self._algorithm.can_load_pellet()
        EventManager.post_event(BehaviorEventKind.pelletLoadCan, context=can)
        return can

    def can_send_pellet(self):
        can = self.can_use_pellet_command()
        EventManager.post_event(BehaviorEventKind.pelletSendCan, context=can)
        return can

    def can_cover_pellet(self):
        can = self.can_use_pellet_command() and self._algorithm.can_cover_pellet()
        EventManager.post_event(BehaviorEventKind.pelletCoverCan, context=can)
        return can

    def can_prerelease_pellet(self):
        can = self.can_use_pellet_command() and self._algorithm.can_release_pellet()
        EventManager.post_event(BehaviorEventKind.pelletPrereleaseCan, context=can)
        return can

    def can_release_pellet(self):
        can = self.can_use_pellet_command() and self._algorithm.can_release_pellet()
        EventManager.post_event(BehaviorEventKind.pelletReleaseCan, context=can)
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

    def _pellet_device_ack_received(self, token):
        if self._api_status_token is None:
            # External command.  Safe to ignore.
            return

        if token != self._api_status_token:
            # External command while we are waiting for our own.  Track in case it is causing conflicts.
            EventManager.post_event(BehaviorEventKind.pelletExternalToken, context=token)
            logger.warning("ignoring pellet delivery token from external command")
            return

        EventManager.post_event(BehaviorEventKind.pelletAcknowledgeToken, context=token)

        self._api_status_token = None

        self._try_next_state()

    # endregion

    def _try_next_state(self, pellet_seen: bool = True, must_release: bool = False):
        # Always arrest to the home position during intersession.
        if self.algorithm.system_state == SystemState.intersession:
            if self.state != PelletState.home:
                self.move_home()
            return

        if self.state == PelletState.loading:
            if self.algorithm.pellet_cover_enabled:
                self.send_pellet()
            else:
                self.prerelease_pellet()
        elif self.state == PelletState.prerelease:
            self.send_pellet()
        elif self.state == PelletState.sending:
            if self.algorithm.pellet_cover_enabled:
                # The hardware ends the send phase with the pellet covered.  Put things in a consistent state of
                # covered without sending an unnecessary command.
                self.state = PelletState.covering
                self.release_pellet()
            else:
                self.monitor_pellet()
        elif self.state == PelletState.covering:
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
                    self.release_pellet()
                elif not pellet_seen:
                    self.load_pellet()
            else:
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

    # endregion
