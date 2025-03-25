import logging
from enum import Enum

from events import Events
from opentelemetry import trace
from transitions import Machine

from autotrainer.core import EventManager, PelletReader

from ..system_machine_state import SystemState
from ..behavior_algorithm import BehaviorAlgorithm, BehaviorLimits
from ..behavior_event_kind import BehaviorEventKind

logger = logging.getLogger(__name__)

tracer = trace.get_tracer("behavior")


class PelletState(str, Enum):
    monitoring = "monitoring",
    loading = "loading"
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
        {"trigger": "send_pellet", "source": [PelletState.loading, PelletState.home],
         "dest": PelletState.sending, "before": "before_send_pellet", "conditions": "can_send_pellet"},
        {"trigger": "cover_pellet", "source": PelletState.monitoring, "dest": PelletState.covering,
         "before": "before_cover_pellet", "conditions": "can_cover_pellet"},
        {"trigger": "release_pellet", "source": [PelletState.covering, PelletState.monitoring],
         "dest": PelletState.releasing, "before": "before_release_pellet",
         "conditions": "can_release_pellet"},
        {"trigger": "monitor_pellet", "source": "*", "dest": PelletState.monitoring},
        {"trigger": "move_home", "source": "*", "dest": PelletState.home, "before": "before_move_home",
         "conditions": "can_move_home"},
    ]

    def __init__(self, algorithm: BehaviorAlgorithm = None, pellet_device: PelletReader = None, pellet_command=None):
        self.state = PelletState.covering

        self.machine = Machine(model=self, states=PelletMachine.states,
                               transitions=PelletMachine.transitions, auto_transitions=False,
                               initial=PelletState.monitoring, model_override=True)

        self._algorithm = algorithm if algorithm is not None else BehaviorAlgorithm(BehaviorLimits())

        self._algorithm.session_starting += self._session_starting
        self._algorithm.session_ending += self._session_ending

        self.pellet_device = pellet_device

        if self.pellet_device is not None:
            self.pellet_device.ack_received += self._pellet_device_ack_received

        self.pellet_command = pellet_command

        self._api_status_token = None

        self._pellet_command_trace = None

        self._events = Events(("pellet_loading", "pellet_sending"))

    @property
    def algorithm(self):
        return self._algorithm

    @property
    def events(self):
        return self._events

    def before_move_home(self):
        if self.pellet_command is not None:
            self._pellet_command_trace = tracer.start_span("move_home")
            self._api_status_token = self.pellet_command.send_home()
            EventManager.post_event(BehaviorEventKind.pelletHomeBegin, context=self._api_status_token)
        else:
            self._api_status_token = None

    def before_load_pellet(self):
        if self.pellet_command is not None:
            self.events.pellet_loading()
            self._pellet_command_trace = tracer.start_span("load_pellet")
            self._api_status_token = self.pellet_command.load_pellet()
            EventManager.post_event(BehaviorEventKind.pelletLoadBegin, context=self._api_status_token)
        else:
            self._api_status_token = None

    def before_send_pellet(self):
        if self.pellet_command is not None:
            self.events.pellet_sending()
            self._api_status_token = self.pellet_command.send_pellet()
            EventManager.post_event(BehaviorEventKind.pelletSendBegin, context=self._api_status_token)
        else:
            self._api_status_token = None

    def after_load_pellet(self):
        self._algorithm.pellet_loaded()

    def before_cover_pellet(self):
        if self.pellet_command is not None:
            self._api_status_token = self.pellet_command.cover_pellet()
            EventManager.post_event(BehaviorEventKind.pelletCoverBegin, context=self._api_status_token)
        else:
            self._api_status_token = None

    def before_release_pellet(self):
        if self.pellet_command is not None:
            self._api_status_token = self.pellet_command.release_pellet()
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

    def can_release_pellet(self):
        can = self.can_use_pellet_command() and self._algorithm.can_release_pellet()
        EventManager.post_event(BehaviorEventKind.pelletReleaseCan, context=can)
        return can

    def can_use_pellet_command(self):
        return self._api_status_token is None

    def pellet_seen(self, seen: bool):
        # if not seen:
        #    if self.state == PelletState.monitoring:
        #         self.load_pellet()
        #     elif self.state == PelletState.covering:
        #         self.load_pellet()
        # else:
        #     if self.state == PelletState.covering:
        #         self.release_pellet()
        self._try_next_state(seen)

    # region Callbacks
    def _session_starting(self):
        # The system may start with a pellet visible and covered depending on the state when last exited.  This will
        # put the system in a monitoring state, rather than covered because we can not query if it is covered. So we
        # may need to release in the monitoring state.
        # We also may have toggled between enabling and disabling the cover behavior, so even if pellet_cover_enabled
        # is false, send the command.
        # if self.state == PelletState.covering or self.state == PelletState.monitoring:
        #     self.release_pellet()
        # elif self.state == PelletState.home:
        #     self.send_pellet()
        self._try_next_state(True, True)

    def _session_ending(self):
        # if self.state == PelletState.monitoring:
        #    self.cover_pellet()
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

        if self._pellet_command_trace is not None:
            self._pellet_command_trace.end()

        EventManager.post_event(BehaviorEventKind.pelletAcknowledgeToken, context=token)

        self._api_status_token = None

        self._try_next_state()

    # endregion

    def _try_next_state(self, pellet_seen: bool = True, must_release: bool = False):
        if self._algorithm.is_in_session:
            if self.state == PelletState.loading:
                self.send_pellet()
            elif self.state == PelletState.sending:
                # The hardware ends the send phase with the pellet covered.  Put things in a consistent state of
                # covered without sending an unnecessary command.
                self.state = PelletState.covering
                self.release_pellet()
            elif self.state == PelletState.covering:
                if pellet_seen:
                    self.release_pellet()
                else:
                    self.load_pellet()
            elif self.state == PelletState.releasing:
                self.monitor_pellet()
            elif self.state == PelletState.home:
                self.send_pellet()
            elif self.state == PelletState.monitoring:
                if must_release:
                    self.release_pellet()
                elif not pellet_seen:
                    self.load_pellet()
        else:
            if self._algorithm.system_state == SystemState.intersession:
                if self.state != PelletState.home:
                    self.move_home()
            else:
                if self.state == PelletState.loading:
                    self.send_pellet()
                elif self.state == PelletState.sending:
                    # The hardware ends the send phase with the pellet covered.  Put things in a consistent state of
                    # covered without sending an unnecessary command.
                    self.state = PelletState.covering
                    self.release_pellet()
                elif self.state == PelletState.covering:
                    if not pellet_seen:
                        self.load_pellet()
                    else:
                        self.release_pellet()
                elif self.state == PelletState.releasing:
                    self.monitor_pellet()
                elif self.state == PelletState.monitoring:
                    if not pellet_seen:
                        self.load_pellet()
                    else:
                        self.cover_pellet()
                elif self.state == PelletState.home:
                    self.send_pellet()

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

    def is_sending(self):
        pass

    def is_covering(self):
        pass

    def is_releasing(self):
        pass

    def is_monitoring(self):
        pass

    # endregion
