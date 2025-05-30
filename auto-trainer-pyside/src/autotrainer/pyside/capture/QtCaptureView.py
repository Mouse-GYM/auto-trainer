from __future__ import annotations

from typing import List, Optional
from collections import namedtuple

from PySide6.QtCore import Qt, Signal, Slot, QSize
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QWidget, QLabel, QComboBox, QHBoxLayout, QVBoxLayout, QStackedLayout

from autotrainer.inference import PoseTuple, PoseAlgorithm
from autotrainer.pyside.CardWidget import CardWidget
from .QtGLImageView import QGLImageView
from .QtCaptureSettings import QCaptureSettings


ImageData = namedtuple("image_data", ("bytes", "width", "height"))


class QCaptureView(QWidget):
    camera_changed = Signal(object)
    recording_indicator_changed = Signal(bool)

    def __init__(self, image_width: int = 420, image_height: int = 280):
        super().__init__()

        self._image_width = image_width
        self._image_height = image_height
        self._fps = 0
        self._cameras = list()

        self._next_frame_data: Optional[ImageData] = None
        self._is_frame_dirty = False

        self._next_frame_points: List[PoseTuple] = []
        self._are_points_dirty = False

        self._card_widget = CardWidget()

        # Header
        self._title = QLabel("Capture")
        self._title.setStyleSheet("font-weight: bold")

        self._camera = QComboBox()
        self._camera.currentIndexChanged.connect(self._source_changed)

        self._camera_name = QLabel("")

        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.addWidget(self._title)
        top_layout.addStretch(1)
        top_layout.addWidget(self._camera)
        top_layout.addWidget(self._camera_name)
        widget = QWidget()
        widget.setLayout(top_layout)
        self._card_widget.header.setContent(widget)

        # Content/Image
        widget = QWidget()
        self._content_stack = QStackedLayout()
        widget.setLayout(self._content_stack)
        self._card_widget.setContentWidget(widget)

        self._image = QGLImageView(image_width, image_height)
        self._image.setFixedSize(QSize(self._image_width, self._image_height))
        self._content_stack.addWidget(self._image)

        # Editable Content
        self._settings = QCaptureSettings()
        self._settings.capture_enabled_changed.connect(lambda x: self._update_summary())
        self._settings.record_enabled_changed.connect(lambda x: self._update_summary())
        self._settings.record_mode_changed.connect(lambda x: self._update_summary())
        self._settings.image_capture_enabled_changed.connect(lambda x: self._update_summary())
        self._settings.image_capture_interval_changed.connect(lambda x: self._update_summary())
        self._content_stack.addWidget(self._settings)

        # Footer
        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        self._status_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        self._is_recording = QLabel("")
        self._is_recording.setStyleSheet("border: 1px solid gray; border-radius: 8; background-color: green;")
        self._is_recording.setFixedSize(16, 16)
        self._is_recording.setVisible(False)

        self._footer = QWidget()
        self._footer.setMinimumHeight(32)
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._status_label, stretch=1)
        layout.addWidget(self._is_recording)
        self._footer.setLayout(layout)

        self._card_widget.footer.setContent(self._footer)

        layout = QVBoxLayout()
        layout.addWidget(self._card_widget)

        self.setLayout(layout)

        self.set_is_editable(False)

        self.recording_indicator_changed.connect(lambda b: self._setRecordingEnabledIndicator(b))

    @Slot(PoseAlgorithm)
    def algo_initialised(self, pose_algo: PoseAlgorithm):
        self._image.set_pose_algo(pose_algo)

    def set_is_capture_active(self, is_active: bool):
        self._camera.setEnabled(not is_active)

        if not is_active:
            self._is_recording.setVisible(False)
        else:
            self._is_recording.setVisible(self._settings.isCaptureEnabled and self._settings.isRecordEnabled
                                          and not self._settings.isTriggerRecordMode)

    def set_is_editable(self, is_editable: bool):
        self._content_stack.setCurrentIndex(1 if is_editable else 0)
        self._camera.setVisible(is_editable)
        self._camera_name.setVisible(not is_editable)

    @property
    def settings(self) -> QCaptureSettings:
        return self._settings

    def setCamera(self, camera):
        if camera in self._cameras:
            self._camera.setCurrentIndex(self._cameras.index(camera))

    def setCameras(self, cameras: list):
        self._cameras = cameras

        self._camera.clear()

        for camera in cameras:
            self._camera.addItem(camera.name, camera)

    def setTitle(self, title: str):
        self._title.setText(title)

    def setSize(self, width: int, height: int):
        self._image_width = width
        self._image_height = height
        self._image.setFixedSize(QSize(self._image_width, self._image_height))

    def setShape(self, width: int, height: int):
        self._image.set_data_size(width, height)

    def update_image(self):
        if self._next_frame_data is None or not self._is_frame_dirty:
            return

        image = QImage(self._next_frame_data.bytes, self._next_frame_data.width, self._next_frame_data.height,
                       QImage.Format_Grayscale8)

        if self._next_frame_data.height != self._image_height or self._next_frame_data.width != self._image_width:
            image = image.scaled(self._image_width, self._image_height, Qt.KeepAspectRatio)

        self._image.set_data(image)

        self._is_frame_dirty = False

        # self._fps_label.setText(f"{self._fps:.1f}")

    @Slot(ImageData, float)
    def refresh_image(self, data: ImageData, fps: float):
        self._next_frame_data = data

        self._is_frame_dirty = True

        if fps != self._fps:
            self._fps = fps

    def update_pose(self):
        if self._next_frame_points is None or not self._are_points_dirty:
            return
        self._image.set_points(self._next_frame_points)
        self._are_points_dirty = False

    @Slot(list)
    def refresh_pose(self, points: List[PoseTuple]):
        self._next_frame_points = points
        self._are_points_dirty = True

    def _source_changed(self, index):
        camera = self._camera.itemData(index)
        if camera:
            self._camera_name.setText(camera.name)
        else:
            self._camera_name.setText("None")
        self.camera_changed.emit(camera)

    def _setRecordingEnabledIndicator(self, b: bool):
        self._is_recording.setVisible(b)

    def _update_summary(self):

        if self._settings.isCaptureEnabled:
            recording = ""
            image_capture = ""

            if self._settings.isRecordEnabled:
                recording = "triggered" if self._settings.isTriggerRecordMode else "continuous"
                recording += " video"

            if self._settings.isImageCaptureEnabled:
                interval = self._settings.imageCaptureInterval
                if interval > 0:
                    image_capture = f"  Image capture every {interval} {'seconds' if interval != 1 else 'second'}."
                    if len(recording) > 0:
                        recording += " and image"
                    else:
                        recording = "triggered" if self._settings.isTriggerRecordMode else "continuous"
                        recording += " image"
                else:
                    image_capture = "  Image capture disabled pending valid interval."

            if len(recording) > 0:
                recording += " recording"
            else:
                recording = "all recording disabled"

            text = f"Capture enabled with {recording}.{image_capture}"
        else:
            text = "Capture disabled."

        self._status_label.setText(text)
