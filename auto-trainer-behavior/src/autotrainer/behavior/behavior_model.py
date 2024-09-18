import logging
import time
from enum import Enum

from transitions import Machine
from transitions.extensions import HierarchicalMachine

from autotrainer.core import TriggerManager, CAPTURE_TRIGGER_ID
from autotrainer.device import HeadFixReader, PelletReader
from autotrainer.inference import PoseAlgorithm2, PoseResponse

from .behavior_model_properties import BehaviorModelProperties, BehaviorModelLimits

logger = logging.getLogger(__name__)

# TODO Configurable property
PELLET_MISSING_TIME = 1.0  # Seconds


class SystemStates(str, Enum):
    InCage = "in-cage"
    PelletDelivery = "pellet-delivery"


class PelletDeliveryStates(str, Enum):
    Idle = "idle"
    Missing = "missing"
    Loading = "loading"
    Sending = "sending"
    Releasing = "releasing"

    def full_name(self):
        return f"{SystemStates.PelletDelivery}_{self}"


class BehaviorModel(object):
    """
    pellet_delivery_states = {"name": SystemStates.PelletDelivery.value, "initial": PelletDeliveryStates.Idle.value,
                              "children": [PelletDeliveryStates.Idle.value, PelletDeliveryStates.Missing.value,
                                           PelletDeliveryStates.Loading.value, PelletDeliveryStates.Sending.value,
                                           PelletDeliveryStates.Releasing.value]}

    states = [SystemStates.InCage.value, pellet_delivery_states]

    transitions = [
        {"trigger": "enter_tunnel", "source": "*", "dest": SystemStates.PelletDelivery.value,
         "before": "before_enter_tunnel"},
        {"trigger": "exit_tunnel", "source": "*", "dest": SystemStates.InCage.value,
         "after": "after_exit_tunnel"},
        {"trigger": "load_pellet", "source": PelletDeliveryStates.Idle.full_name(),
         "dest": PelletDeliveryStates.Loading.full_name(), "before": "before_load_pellet"},
        {"trigger": "send_pellet", "source": PelletDeliveryStates.Loading.full_name(),
         "dest": PelletDeliveryStates.Sending.full_name(), "before": "before_send_pellet"},
        {"trigger": "release_pellet", "source": PelletDeliveryStates.Sending.full_name(),
         "dest": PelletDeliveryStates.Releasing.full_name(), "before": "before_release_pellet",
         "after": "after_release_pellet"},
        {"trigger": "monitor_pellet", "source": PelletDeliveryStates.Releasing.full_name(),
         "dest": PelletDeliveryStates.Idle.full_name()}
    ]
    """
    states = ["in-cage", "monitoring", "loading", "sending", "releasing"]

    transitions = [
        {"trigger": "enter_tunnel", "source": "*", "dest": "monitoring",
         "before": "before_enter_tunnel"},
        {"trigger": "exit_tunnel", "source": "*", "dest": "in-cage",
         "after": "after_exit_tunnel"},
        {"trigger": "my_load_pellet", "source": "monitoring",
         "dest": "loading", "before": "before_load_pellet"},
        {"trigger": "send_pellet", "source": "loading",
         "dest": "sending", "before": "before_send_pellet"},
        {"trigger": "release_pellet", "source": "sending",
         "dest": "releasing", "before": "before_release_pellet",
         "after": "after_release_pellet"},
        {"trigger": "monitor_pellet", "source": "releasing",
         "dest": "monitoring"}
    ]

    def __init__(self, head_fix: HeadFixReader, pellet_device: PelletReader, pellet_command, pose: PoseAlgorithm2):
        super().__init__()

        self.machine = Machine(model=self, states=BehaviorModel.states,
                               transitions=BehaviorModel.transitions,
                               initial="in-cage")

        self._properties = BehaviorModelProperties(BehaviorModelLimits())

        self.head_fix = head_fix

        if self.head_fix is not None:
            self.head_fix.property_changed += self.head_fix_property_changed

        self.pellet_device = pellet_device

        if self.pellet_device is not None:
            self.pellet_device.ack_received += self.pellet_device_ack_received

        self.pellet_command = pellet_command

        self.pose = pose

        if self.pose is not None:
            self.pose.pose_changed += self.pose_changed
            self.pellet_index = self, pose.get_part_index("Pellet")

        self._api_status_token = None

    def before_enter_tunnel(self):
        TriggerManager.instance().trigger(self, CAPTURE_TRIGGER_ID, True)

    def after_exit_tunnel(self):
        TriggerManager.instance().trigger(self, CAPTURE_TRIGGER_ID, False)

    def before_load_pellet(self):
        self._api_status_token = self.pellet_load()
        logger.debug(f"load: waiting for api token: {self._api_status_token}")

    def before_send_pellet(self):
        self._api_status_token = self.pellet_send()
        logger.debug(f"send: waiting for api token: {self._api_status_token}")

    def before_release_pellet(self):
        self._api_status_token = self.pellet_release()
        logger.debug(f"release: waiting for api token: {self._api_status_token}")

    def after_release_pellet(self):
        logger.debug("pellet: delivery cycle complete")

    @property
    def properties(self):
        return self._properties

    def pellet_move_home(self) -> object:
        if self._properties.pellet_delivery_enabled:
            return self.pellet_command.send_home()
        return None

    def pellet_load(self) -> object:
        if self._properties.pellet_delivery_enabled:
            return self.pellet_command.load_pellet()
        return None

    def pellet_send(self) -> object:
        if self._properties.pellet_delivery_enabled:
            return self.pellet_command.send_pellet()
        return None

    def pellet_release(self) -> object:
        if self._properties.pellet_delivery_enabled:
            return self.pellet_command.release_pellet()
        return None

    def head_fix_property_changed(self, name: str, value, _):
        if name == "is_load_cell_engaged":
            if value:
                self.enter_tunnel()
            else:
                self.exit_tunnel()

    def pose_changed(self, response: PoseResponse):
        pellet_seen = response.parts_flag["Pellet"]

        if pellet_seen:
            self.properties.pellet_missing = time.time()
        else:
            if self.state == "monitoring":
                if time.time() - self.properties.pellet_missing >= PELLET_MISSING_TIME:
                    self.my_load_pellet()

    def pellet_device_ack_received(self, token):
        if self.state == "loading":
            self.send_pellet()
        elif self.state == "sending":
            self.release_pellet()
        elif self.state == "releasing":
            self.monitor_pellet()
