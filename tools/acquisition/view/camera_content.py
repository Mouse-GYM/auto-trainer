from numpy import ndarray

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QGridLayout

from autotrainer.core import TriggerManager, CAPTURE_TRIGGER_ID
from autotrainer.pyside.ATCaptureView import image_data
from autotrainer.video import VideoRecordMode
from autotrainer.pyside import ATCaptureView

from tools.acquisition.model.video_capture_model import VideoCaptureModel
from tools.acquisition.view.ContentWidget import ContentWidget


class CameraContent(ContentWidget):
    def __init__(self, model: VideoCaptureModel):
        super().__init__()

        self._model = model

        layout = QGridLayout()

        layout.setContentsMargins(0, 0, 0, 0)

        self._capture_view = ATCaptureView()
        self._capture_view.setIsCaptureEnabled(self._model.is_enabled)
        self._capture_view.setIsRecordingEnabled(self._model.is_recording_enabled)
        self._capture_view.setRecordMode(self._model.record_mode)

        self._capture_view.setCameras(self._model.camera_list)
        self._capture_view.setCamera(self._model.camera_source)

        self._capture_view.camera_changed.connect(self._camera_source_changed)
        self._capture_view.enabled_changed.connect(self._camera_enabled_changed)
        self._capture_view.record_enabled_changed.connect(self._recording_enabled_changed)
        self._capture_view.trigger_source_changed.connect(self._recording_enabled_changed)

        layout.addWidget(self._capture_view)

        self.setLayout(layout)

        TriggerManager.instance().register(self._trigger_received, CAPTURE_TRIGGER_ID)

        self._model.property_changed += self._model_property_changed

    @property
    def camera_view(self) -> ATCaptureView:
        return self._capture_view

    @Slot(ndarray, float)
    def refresh_image(self, data: ndarray, fps: float):
        row, col = data.shape
        self._capture_view.refresh_image(image_data(data.flatten().tobytes(), col, row), fps)

    def set_is_editable(self, is_editable: bool):
        self._capture_view.set_is_editable(is_editable)

    def set_is_capture_active(self, is_active: bool):
        self._capture_view.set_is_capture_active(is_active)

    def update_image(self):
        self._capture_view.update_image()

    def update_pose(self, points):
        self._capture_view.update_pose(points)

    def _camera_source_changed(self, camera):
        self._model.camera_source = camera

    def _camera_enabled_changed(self, is_enabled):
        self._model.is_enabled = is_enabled

    def _recording_enabled_changed(self, is_enabled):
        self._model.is_recording_enabled = is_enabled

        self._model.record_mode = VideoRecordMode.TRIGGER if \
            self._capture_view.is_trigger_record() else VideoRecordMode.CONTINUOUS

    def _trigger_received(self, _, __, context):
        if self._model.is_enabled and self._model.record_mode == VideoRecordMode.TRIGGER:
            self._capture_view.recording_indicator_changed.emit(context)

    def _model_property_changed(self, name, value, _):
        if name == "camera":
            self._capture_view.setCamera(value)
        elif name == "is_enabled":
            self._capture_view.setIsCaptureEnabled(value)
        elif name == "is_recording_enabled":
            self._capture_view.setIsRecordingEnabled(value)
        elif name == "record_mode":
            self._capture_view.setRecordMode(value)
        elif name == "shape":
            if value is not None and value[0] != 0 and value[1] != 0:
                self._capture_view.setShape(value[0], value[1])
