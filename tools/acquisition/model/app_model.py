import logging
import time

from multiprocessing import Queue

from autotrainer.trigger_manager import TriggerManager

from tools.acquisition.model.head_fix_model import HeadFixModel
from tools.acquisition.model.pellet_delivery_model import PelletDeliveryModel
from tools.acquisition.model.user_settings import UserSettings
from tools.acquisition.model.video_capture_model import VideoCaptureModel, CAPTURE_TRIGGER_ID
from tools.acquisition.process.network_merge import NetworkMerge
from tools.acquisition.process.pose_predict import PosePredict

logger = logging.getLogger(__name__)


class AppModel:
    def __init__(self):
        self._user_settings = UserSettings()

        self._network_input_queue_1 = Queue()
        self._network_input_queue_2 = Queue()
        self._network_output_queue = Queue()

        self._left_camera = VideoCaptureModel("left", self._user_settings, None)  # self._network_input_queue_1)
        self._right_camera = VideoCaptureModel("right", self._user_settings, None)  # self._network_input_queue_2)
        self._top_camera = VideoCaptureModel("top", self._user_settings)

        self._network_merge = NetworkMerge(self._network_input_queue_1, self._network_input_queue_2,
                                           self._network_output_queue)
        # self._network_merge.start()

        self._predict = PosePredict(self._network_output_queue, "D:\\rcp\\models\\RTDLC_SimClust-WRW-2019-09-11\\")
        # self._predict.start()

        self._cameras = list([self._left_camera, self._right_camera, self._top_camera])

        self.head_fix = HeadFixModel(self._user_settings)

        self.pellet_delivery = PelletDeliveryModel(self._user_settings)

        self._is_recording_trigger = False

        TriggerManager.instance().register(self._trigger_received, CAPTURE_TRIGGER_ID)

    @property
    def user_settings(self) -> UserSettings:
        return self._user_settings

    @property
    def left_camera(self):
        return self._left_camera

    @property
    def right_camera(self):
        return self._right_camera

    @property
    def top_camera(self):
        return self._top_camera

    def on_capture_start(self) -> bool:
        didStart = True
        for camera in self._cameras:
            res = camera.on_prepare_capture(self._user_settings.output_location)
            didStart = didStart and res
            if not res:
                break

        if not didStart:
            logger.error("failed to start all subprocesses")
            self.on_capture_stop()
            return False

        self.head_fix.connect_to_device()
        self.pellet_delivery.connect_to_device()

        for camera in self._cameras:
            if camera.is_primary:
                camera.on_capture_start()

        for camera in self._cameras:
            if not camera.is_primary:
                camera.on_capture_start()

        return True

    def on_capture_stop(self):
        self.head_fix.disconnect_from_device()
        self.pellet_delivery.disconnect_from_device()

        for camera in self._cameras:
            if not camera.is_primary:
                camera.on_capture_notify_end()

        time.sleep(0.01)

        for camera in self._cameras:
            if camera.is_primary:
                camera.on_capture_notify_end()

        for camera in self._cameras:
            if not camera.is_primary:
                camera.on_capture_stop()

        for camera in self._cameras:
            if camera.is_primary:
                camera.on_capture_stop()

    def toggle_trigger_state(self):
        TriggerManager.instance().trigger(self, CAPTURE_TRIGGER_ID, not self._is_recording_trigger)

    def on_close(self):
        if self._predict.is_alive():
            self._predict.terminate()

        self._network_merge.requestInterruption()
        self._network_merge.wait()

        for camera in self._cameras:
            camera.on_close()

    def _trigger_received(self, sender, trigger_id, context):
        self._is_recording_trigger = context
