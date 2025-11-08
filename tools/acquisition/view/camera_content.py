from typing import Dict

from numpy import ndarray

from PySide6.QtCore import Slot, Qt
from PySide6.QtWidgets import QGridLayout, QSizePolicy

from autotrainer.core import NotificationCenter, TriggerNotification, Notification
from autotrainer.inference import PoseLocation
from autotrainer.core.pose_elements import SceneElement
from autotrainer.pyside.capture.QtCaptureView import ImageData
from autotrainer.video import VideoRecordMode
from autotrainer.pyside import QCaptureView

from tools.acquisition.model.video_capture_model import VideoCaptureModel
from tools.acquisition.view.content_widget import ContentWidget


class CameraContent(ContentWidget):
    def __init__(self, capture_model: VideoCaptureModel):
        super().__init__()

        self._model = capture_model

        layout = QGridLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        capture_view = self._capture_view = QCaptureView()
        self._settings = capture_view.settings
        self._settings.setIsVideoCaptureEnabled(capture_model.is_enabled)
        self._settings.setIsVideoRecordEnabled(capture_model.is_recording_enabled)
        self._settings.setRecordMode(capture_model.record_mode)
        self._settings.setStillImageCaptureEnabled(capture_model.is_still_capture_enabled)
        self._settings.setStillImageCaptureInterval(capture_model.still_image_capture_interval)

        capture_view.setCameras(capture_model.camera_list)
        capture_view.setCamera(capture_model.camera_source)
        capture_view.camera_changed.connect(self._camera_source_changed)

        self._settings.capture_enabled_changed.connect(self._camera_enabled_changed)
        self._settings.record_enabled_changed.connect(self._recording_enabled_changed)
        self._settings.record_mode_changed.connect(self._recording_enabled_changed)
        self._settings.image_capture_enabled_changed.connect(self._is_still_image_capture_enabled_changed)
        self._settings.image_capture_interval_changed.connect(self._still_image_capture_interval_changed)

        layout.addWidget(self._capture_view)

        self.setLayout(layout)

        NotificationCenter.default_center().add_observer(TriggerNotification.CAPTURE_ID, self._trigger_received)

        self._model.property_changed += self._model_property_changed

        # Swap because model shape is row x col == height x width
        capture_view.setShape(self._model.shape[1], self._model.shape[0])
        capture_view.set_presence_detection(capture_model.presence_detection)

    @property
    def camera_view(self) -> QCaptureView:
        return self._capture_view

    @Slot(ndarray, float)
    def refresh_image(self, data: ndarray, fps: float):
        row, col = data.shape
        self._capture_view.refresh_image(ImageData(data, col, row), fps)

    def set_is_editable(self, is_editable: bool):
        self._capture_view.set_is_editable(is_editable)

    def set_is_capture_active(self, is_active: bool):
        self._capture_view.set_is_capture_active(is_active)

    def update_image(self):
        self._capture_view.update_image()
        self._capture_view.update_pose()

    def refresh_pose(self, points: Dict[str, PoseLocation]):
        self._capture_view.refresh_pose(points)

    def _camera_source_changed(self, camera):
        self._model.camera_source = camera

    def _camera_enabled_changed(self, is_enabled):
        self._model.is_enabled = is_enabled

    def _recording_enabled_changed(self, is_enabled):
        self._model.is_recording_enabled = is_enabled

        self._model.record_mode = VideoRecordMode.TRIGGER if \
            self._settings.isTriggerRecordMode else VideoRecordMode.CONTINUOUS

    def _is_still_image_capture_enabled_changed(self, is_enabled):
        self._model.is_still_capture_enabled = is_enabled

    def _still_image_capture_interval_changed(self, interval: float):
        self._model.still_image_capture_interval = interval

    def _trigger_received(self, notification: Notification):
        if self._model.is_enabled and self._model.record_mode == VideoRecordMode.TRIGGER:
            self._capture_view.recording_indicator_changed.emit(notification.context)

    def _model_property_changed(self, name, value, _):
        if name == VideoCaptureModel.CAMERA_PROP:
            self._capture_view.setCamera(value)
        elif name == VideoCaptureModel.IS_ENABLED_PROP:
            self._settings.setIsVideoCaptureEnabled(value)
        elif name == VideoCaptureModel.IS_RECORDING_ENABLED_PROP:
            self._settings.setIsVideoRecordEnabled(value)
        elif name == VideoCaptureModel.RECORD_MODE_PROP:
            self._settings.setRecordMode(value)
        elif name == VideoCaptureModel.IS_STILL_CAPTURE_ENABLED_PROP:
            self._settings.setStillImageCaptureEnabled(value)
        elif name == VideoCaptureModel.STILL_IMAGE_CAPTURE_INTERVAL_PROP:
            self._settings.setStillImageCaptureInterval(value)
        elif name == VideoCaptureModel.SHAPE_PROP:
            if value is not None and value[0] != 0 and value[1] != 0:
                # Swap because model shape is row x col == height x width
                self._capture_view.setShape(value[1], value[0])
        elif name == VideoCaptureModel.CAMERA_LIST_PROP:
            self._capture_view.setCameras(self._model.camera_list)
        elif name == VideoCaptureModel.TEXT_OVERLAY_PROP:
            self._capture_view.set_text_overlay(value)
        elif name == VideoCaptureModel.DISPLAY_DOTS_DETECTION_PROP:
            self._capture_view.set_display_dots_detection(value)