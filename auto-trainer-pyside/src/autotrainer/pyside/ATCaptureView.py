from __future__ import annotations

from collections import namedtuple

from PySide6.QtCore import Qt, Signal, Slot, QSize
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QWidget, QLabel, QCheckBox, QComboBox, QHBoxLayout, QGridLayout, QVBoxLayout

from .CardWidget import CardWidget
from .ATGLImageView import ATGLImageView

image_data = namedtuple("image_data", ("bytes", "width", "height"))


class ATCaptureView(QWidget):
    camera_changed = Signal(object)
    enabled_changed = Signal(bool)
    record_enabled_changed = Signal(bool)
    trigger_source_changed = Signal(bool)
    recording_indicator_changed = Signal(bool)

    def __init__(self, image_width: int = 450, image_height: int = 300):
        super().__init__()

        self._image_width = image_width
        self._image_height = image_height
        self._fps = 0
        self._cameras = list()

        self._title = QLabel("Capture")
        self._title.setStyleSheet("font-weight: bold")

        self._camera = QComboBox()
        self._camera.currentIndexChanged.connect(self._source_changed)

        self._camera_name = QLabel("")

        self._isEnabled = QCheckBox("Enabled")
        self._isEnabled.setChecked(True)
        self._isEnabled.toggled.connect(self._is_enabled_changed)

        self._isRecordEnabled = QCheckBox("Record")
        self._isRecordEnabled.toggled.connect(lambda b: self.record_enabled_changed.emit(b))

        self._is_recording = QLabel("")
        self._is_recording.setStyleSheet("border: 1px solid gray; border-radius: 8; background-color: green;")
        self._is_recording.setFixedSize(16, 16)
        self._is_recording.setVisible(False)

        self._triggerSource = QComboBox()
        self._triggerSource.addItem("Continuous")
        self._triggerSource.addItem("Trigger")
        self._triggerSource.currentIndexChanged.connect(self._trigger_source_index_changed)

        self._status_label = QLabel("")

        self._image = ATGLImageView(bytearray(image_width * image_height), image_width, image_height)
        self._image.setFixedSize(QSize(self._image_width, self._image_height))

        self._next_data: image_data | None = None
        self._is_dirty = False

        self._card_widget = CardWidget()

        # Header
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
        self._card_widget.setContentWidget(self._image)

        # Footer
        bottom_layout = QGridLayout()
        bottom_layout.setContentsMargins(0, 0, 0, 0)

        enabled_layout = QHBoxLayout()
        enabled_layout.addWidget(self._isEnabled)
        recording_layout = QHBoxLayout()
        recording_layout.addWidget(self._isRecordEnabled)
        enabled_layout.addLayout(recording_layout)
        bottom_layout.addLayout(enabled_layout, 0, 0)

        trigger_layout = QHBoxLayout()
        trigger_layout.addWidget(QLabel("Record Mode:"))
        trigger_layout.addWidget(self._triggerSource)
        bottom_layout.addLayout(trigger_layout, 1, 0)

        self._editable_footer = QWidget()
        self._editable_footer.setLayout(bottom_layout)

        self._basic_footer = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._status_label)
        layout.addStretch()
        layout.addWidget(self._is_recording)
        self._basic_footer.setLayout(layout)

        self._footer = QWidget()
        self._footer.setLayout(QVBoxLayout())
        self._footer.layout().setContentsMargins(0, 0, 0, 0)
        self._footer.layout().addWidget(self._basic_footer)
        self._footer.layout().addWidget(self._editable_footer)

        self._card_widget.footer.setContent(self._footer)

        layout = QVBoxLayout()
        layout.addWidget(self._card_widget)

        self.setLayout(layout)

        self.set_is_editable(False)

        self.recording_indicator_changed.connect(lambda b: self._setRecordingEnabledIndicator(b))

    def set_is_capture_active(self, is_active: bool):
        self._triggerSource.setEnabled(not is_active)
        self._isEnabled.setEnabled(not is_active)
        self._camera.setEnabled(not is_active)

        if not is_active:
            self._isRecordEnabled.setEnabled(self._isEnabled.isChecked())
            self._is_recording.setVisible(False)
        else:
            self._isRecordEnabled.setEnabled(False)
            self._is_recording.setVisible(
                self._isEnabled.isChecked() and self._isRecordEnabled.isChecked() and not self.is_trigger_record())

    def set_is_editable(self, is_editable: bool):
        self._basic_footer.setVisible(not is_editable)
        self._editable_footer.setVisible(is_editable)
        self._camera.setVisible(is_editable)
        self._camera_name.setVisible(not is_editable)
        self._status_label.setVisible(not is_editable)
        self._update_summary()

    def setCamera(self, camera):
        if camera in self._cameras:
            self._camera.setCurrentIndex(self._cameras.index(camera))

    def setCameras(self, cameras: list):
        self._cameras = cameras

        self._camera.clear()

        for camera in cameras:
            self._camera.addItem(camera.name, camera)

    def _setRecordingEnabledIndicator(self, b: bool):
        self._is_recording.setVisible(b)

    def setTitle(self, title: str):
        self._title.setText(title)

    def setIsCaptureEnabled(self, enabled: bool):
        self._isEnabled.setChecked(enabled)
        self._update_summary()

    def setIsRecordingEnabled(self, is_recording: bool):
        self._isRecordEnabled.setChecked(is_recording)
        self._update_summary()

    def setRecordMode(self, record_mode: int):
        if record_mode is None:
            self._triggerSource.setCurrentIndex(-1)
        else:
            self._triggerSource.setCurrentIndex(record_mode)
        self._update_summary()

    def setSize(self, width: int, height: int):
        self._image_width = width
        self._image_height = height
        self._image.setFixedSize(QSize(self._image_width, self._image_height))
        image = QImage(bytearray(width * height), width, height, QImage.Format_Grayscale8)
        self._image.set_data(image)

    def is_trigger_record(self):
        return self._triggerSource.currentIndex() == 1

    def update_image(self):
        if self._next_data is None or not self._is_dirty:
            return

        image = QImage(self._next_data.bytes, self._next_data.width, self._next_data.height, QImage.Format_Grayscale8)

        if self._next_data.height != self._image_height or self._next_data.width != self._image_width:
            image = image.scaled(self._image_width, self._image_height, Qt.KeepAspectRatio)

        self._image.set_data(image)

        self._is_dirty = False

        # self._fps_label.setText(f"{self._fps:.1f}")

    def update_pose(self, points):
        self._image.set_points(points)

    @Slot(image_data, float)
    def refresh_image(self, data: image_data, fps: float):
        self._next_data = data

        self._is_dirty = True

        if fps != self._fps:
            self._fps = fps

    def _is_enabled_changed(self, value):
        self._isRecordEnabled.setEnabled(value)
        self.enabled_changed.emit(value)

    def _source_changed(self, index):
        camera = self._camera.itemData(index)
        if camera:
            self._camera_name.setText(camera.name)
        else:
            self._camera_name.setText("None")
        self.camera_changed.emit(camera)

    def _trigger_source_index_changed(self, _):
        self.trigger_source_changed.emit(self._isRecordEnabled.isChecked())

    def _update_summary(self):
        if self._isEnabled.isChecked():
            if self._isRecordEnabled.isChecked():
                recording = "triggered" if self.is_trigger_record() else "continuous"
                recording += " recording enabled"
            else:
                recording = "recording disabled"
            text = f"Capture enabled with {recording}"
        else:
            text = "Capture disabled"
        self._status_label.setText(text)
