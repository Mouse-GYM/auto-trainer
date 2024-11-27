import logging
from enum import Enum

from transitions import Machine

from autotrainer.device import PelletReader
from autotrainer.inference import PoseResponse

from ..inference_protocol import InferenceProtocol
from ..behavior_algorithm import BehaviorAlgorithm, BehaviorLimits
from ..event_manager import EventManager, BehaviorEventKind, EventInfo

logger = logging.getLogger(__name__)


class InferenceState(str, Enum):
    monitoring = "monitoring",
    missing = "missing",
    loading = "loading"
    sending = "sending",
    releasing = "releasing"
    covering = "covering",


class InferenceMachine:
    states = [e for e in InferenceState]

    # Note that transitions have conditions, where applicable.  What may appear to be unconditional calls to cover,
    # release, or otherwise perform pellet transitions will not succeed and perform those actions if these conditions
    # are met.
    transitions = [
        {"trigger": "pellet_lost", "source": "*", "dest": InferenceState.missing},
        {"trigger": "load_pellet", "source": InferenceState.missing, "dest": InferenceState.loading,
         "before": "before_load_pellet", "conditions": "can_load_pellet"},
        {"trigger": "send_pellet", "source": InferenceState.loading, "dest": InferenceState.sending,
         "before": "before_send_pellet", "conditions": "can_send_pellet"},
        {"trigger": "cover_pellet", "source": InferenceState.monitoring, "dest": InferenceState.covering,
         "before": "before_cover_pellet", "after": "after_cover_pellet", "conditions": "can_cover_pellet"},
        {"trigger": "release_pellet", "source": [InferenceState.covering, InferenceState.monitoring],
         "dest": InferenceState.releasing, "before": "before_release_pellet", "after": "after_release_pellet",
         "conditions": "can_release_pellet"},
        {"trigger": "monitor_pellet", "source": "*", "dest": InferenceState.monitoring}
    ]

    def __init__(self, algorithm: BehaviorAlgorithm = None, pellet_device: PelletReader = None, pellet_command=None,
                 inference: InferenceProtocol = None):

        self.state = InferenceState.missing

        self.machine = Machine(model=self, states=InferenceMachine.states,
                               transitions=InferenceMachine.transitions, auto_transitions=False,
                               initial=InferenceState.missing, model_override=True)

        self._algorithm = algorithm if algorithm is not None else BehaviorAlgorithm(BehaviorLimits())

        self._algorithm.session_starting += self._session_starting
        self._algorithm.session_ending += self._session_ending

        self.pellet_device = pellet_device

        if self.pellet_device is not None:
            self.pellet_device.ack_received += self._pellet_device_ack_received

        self.pellet_command = pellet_command

        self._inference = inference

        if self._inference is not None and self._inference.pose_algorithm is not None:
            self._inference.pose_algorithm.pose_changed += self._pose_changed

        self._api_status_token = None

    @property
    def algorithm(self):
        return self._algorithm

    def before_load_pellet(self):
        if self.pellet_command is not None:
            self._api_status_token = self.pellet_command.load_pellet()
            EventManager.instance().post_event(
                EventInfo(BehaviorEventKind.pelletLoadBegin, context=self._api_status_token))
        else:
            self._api_status_token = None

    def before_send_pellet(self):
        if self.pellet_command is not None:
            self._api_status_token = self.pellet_command.send_pellet()
            EventManager.instance().post_event(
                EventInfo(BehaviorEventKind.pelletSendBegin, context=self._api_status_token))
        else:
            self._api_status_token = None

    def before_cover_pellet(self):
        if self.pellet_command is not None:
            self._api_status_token = self.pellet_command.cover_pellet()
            EventManager.instance().post_event(
                EventInfo(BehaviorEventKind.pelletCoverBegin, context=self._api_status_token))
        else:
            self._api_status_token = None

    def before_release_pellet(self):
        if self.pellet_command is not None:
            self._api_status_token = self.pellet_command.release_pellet()
            EventManager.instance().post_event(
                EventInfo(BehaviorEventKind.pelletReleaseBegin, context=self._api_status_token))
        else:
            self._api_status_token = None

    def after_release_pellet(self):
        self._algorithm.pellet_released()

    def after_cover_pellet(self):
        self._algorithm.pellet_covered()

    def can_load_pellet(self):
        can = self.can_use_pellet_command() and self._algorithm.can_load_pellet()
        EventManager.instance().post_event(EventInfo(BehaviorEventKind.pelletLoadCan, context=can))
        return can

    def can_send_pellet(self):
        can = self.can_use_pellet_command()
        EventManager.instance().post_event(EventInfo(BehaviorEventKind.pelletSendCan, context=can))
        return can

    def can_cover_pellet(self):
        can = self.can_use_pellet_command() and self._algorithm.can_cover_pellet()
        EventManager.instance().post_event(EventInfo(BehaviorEventKind.pelletCoverCan, context=can))
        return can

    def can_release_pellet(self):
        can = self.can_use_pellet_command() and self._algorithm.can_release_pellet()
        EventManager.instance().post_event(EventInfo(BehaviorEventKind.pelletReleaseCan, context=can))
        return can

    def can_use_pellet_command(self):
        return self._api_status_token is None

    # region Callbacks
    def _session_starting(self):
        # The system may start with a pellet visible and covered depending on the state when last exited.  This will
        # put the system in a monitoring state, rather than covered because we can not query if it is covered. So we
        # may need to release in the monitoring state.
        # We also may have toggled between enabling and disabling the cover behavior, so even if pellet_cover_enabled
        # is false, send the command.
        if self.state == InferenceState.covering or self.state == InferenceState.monitoring:
            self.release_pellet()

    def _session_ending(self):
        if self.state == InferenceState.monitoring:
            self.cover_pellet()

    def _pose_changed(self, response: PoseResponse):
        # TODO reset if in the loading process and pellet seen?

        self._algorithm.pellet_seen(response.pellet_seen)

        self._algorithm.mouse_seen(response.mouse_seen)

        if not self._algorithm.pellet_delivery_enabled:
            return

        if not response.pellet_seen:
            if self.state == InferenceState.monitoring:
                self.pellet_lost()

            if self.state == InferenceState.missing:
                # Immediately go to missing, but load_pellet transition will only succeed if time, pellet limits, and
                # other requirements are satisfied.
                self.load_pellet()
            elif self.state == InferenceState.covering:
                self.pellet_lost()
        else:
            if self.state == InferenceState.missing:
                self.monitor_pellet()
            elif self.state == InferenceState.covering:
                self.release_pellet()

    def _pellet_device_ack_received(self, token):
        if self._api_status_token is None:
            # External command.  Safe to ignore.
            return

        if token != self._api_status_token:
            # External command while we are waiting for our own.  Track in case it is causing conflicts.
            EventManager.instance().post_event(EventInfo(BehaviorEventKind.pelletExternalToken, context=token))
            logger.warning("ignoring pellet delivery token from external command")
            return

        EventManager.instance().post_event(EventInfo(BehaviorEventKind.pelletAcknowledgeToken, context=token))

        self._api_status_token = None

        if self.state == InferenceState.loading:
            self.send_pellet()
        elif self.state == InferenceState.sending:
            # Strictly speaking, the hardware ends the send phase with the pellet covered.  This is primarily to put
            # things in a consistent state of covered whether it is right after sending, or if it was recovered for
            # any reason.
            self.state = InferenceState.covering
            self.release_pellet()
        elif self.state == InferenceState.covering:
            # Will occur after an actual cover command to the hardware.
            self.release_pellet()
        elif self.state == InferenceState.releasing:
            self.monitor_pellet()

    # endregion

    # region State Machine Requirements
    # Methods required for model_override=True to work.
    def trigger(self):
        pass

    def may_trigger(self):
        pass

    def pellet_lost(self):
        pass

    def may_pellet_lost(self):
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

    def is_missing(self):
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
