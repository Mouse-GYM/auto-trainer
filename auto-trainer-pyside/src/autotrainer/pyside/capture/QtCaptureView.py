from __future__ import annotations

import dataclasses
from typing import List, Optional, Dict

import numpy
from PySide6.QtCore import Qt, Signal, Slot, QSize
from PySide6.QtGui import QImage, QPainter, QTextDocument
from PySide6.QtWidgets import QWidget, QLabel, QComboBox, QHBoxLayout, QVBoxLayout, QStackedLayout, QSizePolicy

from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.video_detection import PresenceDetectionAttrs

from autotrainer.inference import PoseLocation

from autotrainer.pyside.CardWidget import CardWidget

from autotrainer.pyside.StackedContent import StackedLayout
from autotrainer.pyside.capture.QtGLImageView import QGLImageView
from autotrainer.pyside.capture.QtCaptureSettings import QCaptureSettings


logger = get_verbose_logger(__name__)


@dataclasses.dataclass
class ImageData:
    array: numpy.ndarray
    width: int
    height: int


class QCaptureView(QWidget):
    camera_changed = Signal(object)
    recording_indicator_changed = Signal(bool)

    def __init__(self, image_width: int = 420, image_height: int = 280):
        super().__init__()

        self._text_overlay: Optional[str] = None
        self._text_color: Qt.GlobalColor = Qt.GlobalColor.yellow
        self._image_width = image_width
        self._image_height = image_height
        self._fps = 0
        self._cameras = list()

        self._next_frame_data: Optional[ImageData] = None
        self._is_frame_dirty = False

        self._next_frame_points: Dict[str, PoseLocation] = {}
        self._are_points_dirty = False
        self._display_dots_detection = True
        self._presence_detection: Optional[PresenceDetectionAttrs] = None

        # Header
        self._camera = QComboBox()
        self._camera.currentIndexChanged.connect(self._source_changed)

        self._camera_name_label = QLabel("")

        top_layout = QHBoxLayout()
        top_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.addWidget(self._camera)
        top_layout.addWidget(self._camera_name_label)

        self._card_widget = CardWidget(title="Capture", header_right_layout=top_layout)

        # Content/Image
        widget = QWidget()
        widget.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        widget.setContentsMargins(0, 0, 0, 0)
        self._content_stack = StackedLayout()
        self._content_stack.setSpacing(0)
        self._content_stack.setContentsMargins(0, 0, 0, 0)
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
        footer = self._footer = QWidget()
        footer.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        footer_layout = QHBoxLayout(footer)
        footer_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        footer_layout.setContentsMargins(0, 0, 0, 0)

        label = self._status_label = QLabel("")
        label.setWordWrap(True)
        label.setContentsMargins(0, 0, 0, 0)
        label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # this really makes sure that the label will expand as necessary when its text is changed
        lbl_l = QVBoxLayout()
        lbl_l.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        lbl_l.addWidget(label)
        footer_layout.addLayout(lbl_l)

        #
        label = self._is_recording = QLabel("")
        label.setStyleSheet("border: 1px solid gray; border-radius: 8; background-color: green;")
        label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        label.setFixedSize(16, 16)
        label.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        label.setVisible(False)
        label.setAlignment(Qt.AlignmentFlag.AlignRight)
        footer_layout.addWidget(self._is_recording, alignment=Qt.AlignmentFlag.AlignRight)

        self._card_widget.footer.setContent(footer)
        footer.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        final_layout = QVBoxLayout()
        final_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        final_layout.addWidget(self._card_widget)
        final_layout.setContentsMargins(0, 0, 0, 0)
        final_layout.setSpacing(0)

        self.setLayout(final_layout)

        self.set_is_editable(False)

        self.recording_indicator_changed.connect(self._set_recording_enabled_indicator)

    @property
    def settings(self) -> QCaptureSettings:
        return self._settings

    @property
    def image_view(self) -> QGLImageView:
        return self._image

    def set_presence_detection(self, detection: Optional[PresenceDetectionAttrs]):
        self._presence_detection = detection

    def set_text_overlay(self, value: str, color: Qt.GlobalColor = Qt.GlobalColor.yellow):
        logger.debug("got new text overlay: %r", value)
        self._text_overlay = value
        self._text_color = color
        self._is_frame_dirty = True
        self.update_image()

    def set_display_dots_detection(self, value):
        self._display_dots_detection = value
        self._is_frame_dirty = True

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
        self._camera_name_label.setVisible(not is_editable)

    def setCamera(self, camera):
        if camera in self._cameras:
            self._camera.setCurrentIndex(self._cameras.index(camera))

    def setCameras(self, cameras: list):
        self._cameras = cameras

        self._camera.clear()

        for camera in cameras:
            self._camera.addItem(camera.name, camera)

    def setTitle(self, title: str):
        self._card_widget.header.setTitle(title)

    def setSize(self, width: int, height: int):
        self._image_width = width
        self._image_height = height
        self._image.setFixedSize(QSize(self._image_width, self._image_height))

    def setShape(self, width: int, height: int):
        logger.verbose("setShape[%s]: w=%s h=%s", self._camera_name_label.text(), width, height)
        self._image.set_data_size(width, height)

    def update_image(self):
        if not self._is_frame_dirty:
            return

        frame = self._next_frame_data
        if frame is None:
            image = QImage(  # noqa
                self._image_width, self._image_height,
                QImage.Format.Format_Grayscale8,
            )
            image.fill(Qt.GlobalColor.black)
        else:
            image = QImage(  # noqa
                frame.array,  # frame.array.data can also be used
                frame.width, frame.height,
                QImage.Format.Format_Grayscale8,
            )
            image = image.scaled(self._image_width, self._image_height,
                                 # NB: this keep the aspect ratio of the image:
                                 Qt.AspectRatioMode.KeepAspectRatio,
                                 # so result image may not be same than requested W x H
                                 )
        if (image.width(), image.height()) == (self._image_width, self._image_height):
            self._image.set_scale_aspect_ratio(1, 1)
        else:
            scale_w = image.width() / self._image_width
            scale_h = image.height() / self._image_height
            self._image.set_scale_aspect_ratio(scale_w, scale_h)
            padded = QImage(self._image_width, self._image_height, image.format())
            padded.fill(Qt.GlobalColor.black)
            painter = QPainter(padded)
            with painter:
                painter.drawImage(0, 0, image)
            image = padded

        self._image.set_data(
            image,
            text_overlay=self._text_overlay,
            text_color=self._text_color,
            presence_detection=self._presence_detection,
        )
        self._is_frame_dirty = False

    @Slot(ImageData, float)
    def refresh_image(self, data: ImageData, fps: float):
        self._next_frame_data = data
        self._is_frame_dirty = True
        if fps != self._fps:
            self._fps = fps

    def update_pose(self):
        if not self._display_dots_detection:
            self._image.set_points({})
            return
        if self._next_frame_points is None or not self._are_points_dirty:
            return
        self._image.set_points(self._next_frame_points)
        self._are_points_dirty = False

    @Slot(dict)
    def refresh_pose(self, points: Dict[str, PoseLocation]):
        self._next_frame_points = points
        self._are_points_dirty = True

    def _source_changed(self, index):
        camera = self._camera.itemData(index)
        if camera:
            self._camera_name_label.setText(camera.name)
        else:
            self._camera_name_label.setText("None")
        self.camera_changed.emit(camera)

    def _set_recording_enabled_indicator(self, b: bool):
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
        self._status_label.update()
        self.update()
