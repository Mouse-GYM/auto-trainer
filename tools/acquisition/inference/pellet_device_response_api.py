from autotrainer.inference import PoseResponseApi

from tools.acquisition.model.pellet_delivery_model import PelletDeliveryModel


class PelletDeviceResponseApi(PoseResponseApi):
    def __init__(self, model, device: PelletDeliveryModel):
        super(PoseResponseApi, self).__init__()
        self._analysis_model = model
        self._pellet_device = device
        self._is_enabled = True

    def set_state_enabled(self, b):
        self._is_enabled = b
        self._analysis_model.is_pose_predict_enabled = b

    def move_home(self) -> object:
        if self._is_enabled:
            return self._pellet_device.send_home()
        return None

    def load_pellet(self) -> object:
        if self._is_enabled:
            return self._pellet_device.load_pellet()
        return None

    def send_pellet(self) -> object:
        if self._is_enabled:
            return self._pellet_device.send_pellet()
        return None

    def release_pellet(self) -> object:
        if self._is_enabled:
            return self._pellet_device.release_pellet()
        return None
