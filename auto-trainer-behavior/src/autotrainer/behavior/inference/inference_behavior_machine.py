import logging
from enum import Enum

from transitions.extensions import HierarchicalMachine

from autotrainer.device import PelletReader
from autotrainer.inference import PoseAlgorithm, PoseResponse

from ..behavior_algorithm import BehaviorAlgorithm

logger = logging.getLogger(__name__)


class InferenceState(str, Enum):
    monitoring = "monitoring",
    loading = "loading"
    sending = "sending"
    releasing = "releasing"


class InferenceBehaviorMachine:
    states = [e for e in InferenceState]

    transitions = [
        {"trigger": "load_pellet", "source": InferenceState.monitoring, "dest": InferenceState.loading,
         "before": "before_load_pellet", "conditions": "can_load_pellet"},
        {"trigger": "send_pellet", "source": InferenceState.loading, "dest": InferenceState.sending,
         "before": "before_send_pellet"},
        {"trigger": "release_pellet", "source": InferenceState.sending, "dest": InferenceState.releasing,
         "before": "before_release_pellet", "conditions": "can_release_pellet"},
        {"trigger": "monitor_pellet", "source": "*", "dest": InferenceState.monitoring}
    ]

    def __init__(self, properties: BehaviorAlgorithm, pellet_device: PelletReader, pellet_command,
                 pose: PoseAlgorithm):
        self.state = InferenceState.monitoring

        self.machine = HierarchicalMachine(model=self, states=InferenceBehaviorMachine.states,
                                           transitions=InferenceBehaviorMachine.transitions, auto_transitions=False,
                                           initial=InferenceState.monitoring, model_override=True)

        self._properties = properties

        self.pellet_device = pellet_device

        if self.pellet_device is not None:
            self.pellet_device.ack_received += self.pellet_device_ack_received

        self.pellet_command = pellet_command

        self.pose = pose

        if self.pose is not None:
            self.pose.pose_changed += self.pose_changed

        self._api_status_token = None

    def before_load_pellet(self):
        self._api_status_token = self.pellet_load()

    def before_send_pellet(self):
        self._api_status_token = self.pellet_send()

    def before_release_pellet(self):
        self._api_status_token = self.pellet_release()

    def can_load_pellet(self):
        return self._properties.pellet_delivery_enabled

    def can_release_pellet(self):
        return self._properties.can_release_pellet()

    @property
    def properties(self):
        return self._properties

    def pellet_move_home(self) -> object:
        if self._properties.pellet_delivery_enabled and self.pellet_command is not None:
            return self.pellet_command.send_home()
        return None

    def pellet_load(self) -> object:
        if self._properties.pellet_delivery_enabled and self.pellet_command is not None:
            return self.pellet_command.load_pellet()
        return None

    def pellet_send(self) -> object:
        if self._properties.pellet_delivery_enabled and self.pellet_command is not None:
            return self.pellet_command.send_pellet()
        return None

    def pellet_release(self) -> object:
        if self._properties.pellet_delivery_enabled and self.pellet_command is not None:
            return self.pellet_command.release_pellet()
        return None

    def pose_changed(self, response: PoseResponse):
        # TODO reset if in the loading process and pellet seen?

        self.properties.pellet_seen(response.pellet_seen)

        self._properties.mouse_seen(response.mouse_seen)

        if not response.pellet_seen:
            if self.state == InferenceState.monitoring:
                self.load_pellet()
            elif self.state == InferenceState.sending:
                self.release_pellet()

    def pellet_device_ack_received(self, token):
        if token != self._api_status_token:
            logger.warning("pellet delivery token mismatch")

        if self.state == InferenceState.loading:
            self.send_pellet()
        elif self.state == InferenceState.sending:
            self.release_pellet()
        elif self.state == InferenceState.releasing:
            self.properties.pellet_released()
            self.monitor_pellet()

    def trigger(self):
        pass

    def may_trigger(self):
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

    def monitor_pellet(self):
        pass

    def may_monitor_pellet(self):
        pass

    def is_monitoring(self):
        pass

    def is_loading(self):
        pass

    def is_sending(self):
        pass

    def is_releasing(self):
        pass
