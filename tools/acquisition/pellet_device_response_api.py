from autotrainer.pose_response_api import PoseResponseApi

from tools.acquisition.model.pellet_delivery_model import PelletDeliveryModel


class PelletDeviceResponseApi(PoseResponseApi):
    def __init__(self, device: PelletDeliveryModel):
        super(PoseResponseApi, self).__init__()
        self._pellet_device = device

    def move_home(self) -> object:
        return self._pellet_device.send_home()

    def load_pellet(self) -> object:
        return self._pellet_device.load_pellet()

    def send_pellet(self) -> object:
        return self._pellet_device.send_pellet()

    def release_pellet(self) -> object:
        return self._pellet_device.release_pellet()
