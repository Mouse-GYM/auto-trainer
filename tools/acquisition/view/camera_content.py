from numpy import ndarray

from PySide6.QtCore import Slot, QTimer
from PySide6.QtWidgets import QGridLayout

from autotrainer.ATCaptureView import ATCaptureView
from autotrainer.video_record_properties import VideoRecordMode

from tools.acquisition.model.video_capture_model import VideoCaptureModel


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

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update_image)
        self._timer.start(1000/30)

    @Slot(ndarray, float)
    def refresh_image(self, data: ndarray, fps: float):
        self._camera_view.refresh_image(data, fps)

    @Slot()
    def update_image(self):
        self._camera_view.update_image()

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
