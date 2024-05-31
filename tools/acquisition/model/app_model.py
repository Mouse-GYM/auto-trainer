import logging
import time

from autotrainer.video import TriggerManager
from autotrainer.core import FixedArrayMultiQueue

from tools.acquisition.model.analysis_model import AnalysisModel
from tools.acquisition.model.head_fix_model import HeadFixModel
from tools.acquisition.model.pellet_delivery_model import PelletDeliveryModel
from tools.acquisition.model.user_settings import UserSettings
from tools.acquisition.model.video_capture_model import VideoCaptureModel, CAPTURE_TRIGGER_ID

logger = logging.getLogger(__name__)


class AppModel:
    def __init__(self):
        self._user_settings = UserSettings()

        self._left_camera = VideoCaptureModel("left", self._user_settings, 0)
        self._right_camera = VideoCaptureModel("right", self._user_settings, 1)
        self._top_camera = VideoCaptureModel("web", self._user_settings, -1)

        self._cameras = list([self._left_camera, self._right_camera, self._top_camera])

        self._head_fix = HeadFixModel(self._user_settings)

        self.pellet_delivery = PelletDeliveryModel(self._user_settings)

        self._network_buffer = None

        self._analysis = AnalysisModel(self._user_settings, self.pellet_delivery)

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

    @property
    def analysis(self):
        return self._analysis

    @property
    def head_fix(self):
        return self._head_fix

    def on_activated(self):
        self._analysis.on_activated()

    def on_capture_start(self) -> bool:
        location, session_index = self._user_settings.get_next_session_path()

        self._network_buffer = None

        if self._analysis.is_enabled:
            shape_1 = self.left_camera.shape
            shape_2 = self.right_camera.shape
            if shape_1 == shape_2:
                self._network_buffer = FixedArrayMultiQueue(3, 2, 3, shape_1)

        did_start = self.left_camera.on_prepare_capture(location, self._network_buffer)

        if did_start:
            did_start = did_start and self.right_camera.on_prepare_capture(location, self._network_buffer)

        if did_start:
            did_start = did_start and self.top_camera.on_prepare_capture(location)

        if not did_start:
            logger.error("failed to start all subprocesses")
            self.on_capture_stop()
            return False

        if self._analysis.is_enabled:
            self._analysis.start(self._network_buffer)

        self._user_settings.session_index = session_index + 1

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
        self._analysis.stop()

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
        if self._analysis is not None:
            self._analysis.terminate()

        for camera in self._cameras:
            camera.on_close()

        self.head_fix.on_close()
        self.pellet_delivery.on_close()

    def _trigger_received(self, sender, trigger_id, context):
        self._is_recording_trigger = context
