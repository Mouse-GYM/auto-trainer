import logging
from enum import Enum

from transitions.extensions import HierarchicalMachine

from autotrainer.device import PelletReader
from autotrainer.inference import PoseAlgorithm, PoseResponse

from ..behavior_algorithm import BehaviorAlgorithm

logger = logging.getLogger(__name__)


class InferenceState(str, Enum):
    monitoring = "monitoring",
    missing = "missing",
    loading = "loading"
    covering = "covering",
    releasing = "releasing"


class InferenceBehaviorMachine:
    states = [e for e in InferenceState]

    transitions = [
        {"trigger": "pellet_lost", "source": InferenceState.monitoring, "dest": InferenceState.missing,
         "before": "before_load_pellet", "conditions": "can_load_pellet"},
        {"trigger": "load_pellet", "source": InferenceState.missing, "dest": InferenceState.loading,
         "before": "before_load_pellet", "conditions": "can_load_pellet"},
        {"trigger": "send_pellet", "source": InferenceState.loading, "dest": InferenceState.covering,
         "before": "before_send_pellet"},
        {"trigger": "cover_pellet", "source": InferenceState.monitoring, "dest": InferenceState.covering,
         "before": "before_send_pellet", "after": "after_cover_pellet"},
        {"trigger": "release_pellet", "source": InferenceState.covering, "dest": InferenceState.releasing,
         "before": "before_release_pellet", "after": "after_release_pellet", "conditions": "can_release_pellet"},
        {"trigger": "monitor_pellet", "source": "*", "dest": InferenceState.monitoring}
    ]

    def __init__(self, algorithm: BehaviorAlgorithm, pellet_device: PelletReader = None, pellet_command=None,
                 pose: PoseAlgorithm = None):

        self.state = InferenceState.missing

        self.machine = HierarchicalMachine(model=self, states=InferenceBehaviorMachine.states,
                                           transitions=InferenceBehaviorMachine.transitions, auto_transitions=False,
                                           initial=InferenceState.missing, model_override=True)

        self._algorithm = algorithm

        self.pellet_device = pellet_device

        if self.pellet_device is not None:
            self.pellet_device.ack_received += self.pellet_device_ack_received

        self.pellet_command = pellet_command

        self.pose = pose

        if self.pose is not None:
            self.pose.pose_changed += self.pose_changed

        self._in_tunnel = False

        self._api_status_token = None

    def before_enter_tunnel(self):
        self._in_tunnel = True

        if self.state == InferenceState.covering:
            self.release_pellet()

    def after_exit_tunnel(self):
        self._in_tunnel = False

        if self.state == InferenceState.monitoring:
            self.cover_pellet()

    def before_load_pellet(self):
        if self._algorithm.pellet_delivery_enabled and self.pellet_command is not None:
            self._api_status_token = self.pellet_command.load_pellet()
        else:
            self._api_status_token = None

    def before_send_pellet(self):
        if self._algorithm.pellet_delivery_enabled and self.pellet_command is not None:
            self._api_status_token = self.pellet_command.send_pellet()
        else:
            self._api_status_token = None

    def before_release_pellet(self):
        if self._algorithm.pellet_delivery_enabled and self.pellet_command is not None:
            self._api_status_token = self.pellet_command.release_pellet()
        else:
            self._api_status_token = None

    def after_release_pellet(self):
        self._algorithm.pellet_released()

    def after_cover_pellet(self):
        self._algorithm.pellet_covered()

    def can_load_pellet(self):
        return self._algorithm.can_load_pellet()

    def can_release_pellet(self):
        return self._in_tunnel and self._algorithm.can_release_pellet()

    @property
    def is_in_tunnel(self):
        return self._in_tunnel

    # region Callbacks
    def pose_changed(self, response: PoseResponse):
        # TODO reset if in the loading process and pellet seen?

        self._algorithm.pellet_seen(response.pellet_seen)

        self._algorithm.mouse_seen(response.mouse_seen)

        if not response.pellet_seen:
            if self.state == InferenceState.monitoring:
                self.pellet_lost()
            if self.state == InferenceState.missing:
                self.load_pellet()
            elif self.state == InferenceState.covering:
                self.release_pellet()

    def pellet_device_ack_received(self, token):
        if token != self._api_status_token:
            logger.warning("pellet delivery token mismatch")

        if self.state == InferenceState.loading:
            self.send_pellet()
        elif self.state == InferenceState.covering:
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

    def is_covering(self):
        pass

    def is_releasing(self):
        pass

    def is_monitoring(self):
        pass

    # endregion
