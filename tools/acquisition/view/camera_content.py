from numpy import ndarray

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QGridLayout

from autotrainer.pyside import ATCaptureView
from autotrainer.video import VideoRecordMode
from autotrainer.video import TriggerManager

from tools.acquisition.model.video_capture_model import VideoCaptureModel

CAPTURE_TRIGGER_ID = "CaptureTrigger"


class CameraContent(QGridLayout):
    def __init__(self, view_model: VideoCaptureModel, camera_list: list):
        super().__init__()

        self._view_model = view_model

        self._camera_view = ATCaptureView()

        self._camera_view.update_cameras(camera_list)
        self._camera_view.camera_selected.connect(self._camera_source_changed)
        self._camera_view.enabled_changed.connect(self._camera_enabled_changed)
        self._camera_view.record_enabled_changed.connect(self._recording_enabled_changed)
        self._camera_view.trigger_source_changed.connect(self._recording_enabled_changed)

        self.addWidget(self._camera_view)

        self._view_model.is_enabled = True
        self._view_model.camera_source = camera_list[0].url

        TriggerManager.instance().register(self._trigger_received, CAPTURE_TRIGGER_ID)

    @Slot(ndarray, float)
    def refresh_image(self, data: ndarray, fps: float):
        self._camera_view.refresh_image(data, fps)

    def update_image(self):
        self._camera_view.update_image()

    def update_pose(self, points):
        self._camera_view.update_pose(points)

    @property
    def camera_view(self) -> ATCaptureView:
        return self._camera_view

    def setCaptureEnabled(self, enabled: bool):
        self._camera_view.setCaptureEnabled(enabled)

    def _camera_source_changed(self, camera):
        self._view_model.camera_source = camera.url

    def _camera_enabled_changed(self, is_enabled):
        self._view_model.is_enabled = is_enabled

    def _recording_enabled_changed(self, is_enabled):
        if is_enabled:
            self._view_model.record_mode = VideoRecordMode.TRIGGER if self._camera_view.is_trigger_record() else VideoRecordMode.CONTINUOUS
        else:
            self._view_model.record_mode = VideoRecordMode.NONE

    def _trigger_received(self, sender, trigger_id, context):
        if self._view_model.is_enabled and self._view_model.record_mode == VideoRecordMode.TRIGGER:
            self._camera_view.setRecordingEnabledIndicator(context)
