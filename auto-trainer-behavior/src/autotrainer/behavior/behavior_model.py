import logging
import time

from .behavior_model_base import BehaviorModelBaseModel, PelletDeliveryStates
from autotrainer.core import TriggerManager, CAPTURE_TRIGGER_ID
from autotrainer.device import HeadFixReader, PelletReader
from autotrainer.inference import PoseAlgorithm, PoseResponse

from .behavior_model_properties import BehaviorModelProperties, BehaviorModelLimits

logger = logging.getLogger(__name__)


class BehaviorModel(BehaviorModelBaseModel):
    def __init__(self, head_fix: HeadFixReader, pellet_device: PelletReader, pellet_command, pose: PoseAlgorithm):
        super().__init__()

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

    # noinspection PyMethodMayBeStatic
    def after_release_pellet(self):
        logger.debug("pellet: delivery cycle complete")

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
            # TODO reset if in the loading process
        else:
            if self.state == PelletDeliveryStates.monitoring:
                if time.time() - self.properties.pellet_missing >= self._properties.limits.pellet_missing_time:
                    self.my_load_pellet()

    def pellet_device_ack_received(self, _token):
        if self.state == PelletDeliveryStates.loading:
            self.send_pellet()
        elif self.state == PelletDeliveryStates.sending:
            self.release_pellet()
        elif self.state == PelletDeliveryStates.releasing:
            self.monitor_pellet()
