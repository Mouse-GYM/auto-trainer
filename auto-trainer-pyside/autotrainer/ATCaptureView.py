from PySide6.QtCore import Qt, Signal, Slot, QSize
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QWidget, QLabel, QCheckBox, QComboBox, QHBoxLayout, QGridLayout
from numpy import ndarray

from .ATImageView import ATImageView


class ATCaptureView(QWidget):
    camera_selected = Signal(object)
    enabled_changed = Signal(bool)
    record_enabled_changed = Signal(bool)
    trigger_source_changed = Signal(bool)

    def __init__(self, title: str = "Capture", image_width: int = 256, image_height: int = 256):
        super().__init__()

        self._image_width = image_width
        self._image_height = image_height
        self._fps = 0

        self._title = QLabel(title)

        self._source = QComboBox()
        self._source.currentIndexChanged.connect(self.source_changed)

        self._isEnabled = QCheckBox("Enabled")
        self._isEnabled.setChecked(True)
        self._isEnabled.toggled.connect(self._is_enabled_changed)

        self._isRecordEnabled = QCheckBox("Record")
        self._isRecordEnabled.toggled.connect(lambda b: self.record_enabled_changed.emit(b))

        self._triggerSource = QComboBox()
        self._triggerSource.addItem("Continuous")
        self._triggerSource.addItem("Trigger")
        self._triggerSource.currentIndexChanged.connect(self._trigger_source_index_changed)

        self._image = ATImageView(bytearray(image_width * image_height), image_width, image_height)
        self._image.setFixedSize(QSize(self._image_width, self._image_height))

        self._next_data = None
        self._is_dirty = False

        layout = QGridLayout()

        top_layout = QHBoxLayout()
        top_layout.addWidget(self._title)
        top_layout.addWidget(self._source)
        layout.addLayout(top_layout, 0, 0)

        layout.addWidget(self._image, 1, 0)

        layout.setRowStretch(2, 1)

        enabled_layout = QHBoxLayout()
        enabled_layout.addWidget(self._isEnabled)
        enabled_layout.addWidget(self._isRecordEnabled)
        layout.addLayout(enabled_layout, 3, 0)

        self._trigger_layout = QHBoxLayout()
        self._trigger_layout.addWidget(QLabel("Record Mode:"))
        self._trigger_layout.addWidget(self._triggerSource)
        layout.addLayout(self._trigger_layout, 4, 0)

        fps_layout = QHBoxLayout()
        fps_layout.addWidget(QLabel("FPS (approx):"))
        self._fps_label = QLabel("0")
        self._fps_label.setAlignment(Qt.AlignLeft)
        fps_layout.addWidget(self._fps_label)

        queue_layout = QHBoxLayout()
        # queue_layout.addWidget(QLabel("Queue:"))
        self._queue_label = QLabel("0")
        self._queue_label.setAlignment(Qt.AlignLeft)
        # queue_layout.addWidget(self._queue_label)

        bottom_layout = QHBoxLayout()
        bottom_layout.addLayout(fps_layout)
        bottom_layout.addLayout(queue_layout)
        # layout.addLayout(bottom_layout, 5, 0)

        self.setLayout(layout)

    def setCaptureEnabled(self, enabled: bool):
        self._triggerSource.setEnabled(enabled)
        self._isEnabled.setEnabled(enabled)
        self._source.setEnabled(enabled)

        if enabled:
            self._isRecordEnabled.setEnabled(self._isEnabled.isChecked())
        else:
            self._isRecordEnabled.setEnabled(False)

    def setTitle(self, title: str):
        self._title.setText(title)

    def set_size(self, width: int, height: int):
        self._image_width = width
        self._image_height = height
        self._image.setFixedSize(QSize(self._image_width, self._image_height))
        image = QImage(bytearray(width * height), width, height, QImage.Format_Grayscale8)
        self._image.set_data(image)

    def is_trigger_record(self):
        return self._triggerSource.currentIndex() == 1

    def _is_enabled_changed(self, value):
        self.enabled_changed.emit(value)
        self._isRecordEnabled.setEnabled(value)

    def source_changed(self, index):
        self.camera_selected.emit(self._source.itemData(index))

    def update_cameras(self, cameras: list):
        self._source.clear()

        for camera in cameras:
            self._source.addItem(camera.name, camera)

    def _trigger_source_index_changed(self, index):
        self.trigger_source_changed.emit(self._isRecordEnabled.isChecked())

    def update_image(self):
        if self._next_data is None or not self._is_dirty:
            return

        x, y = self._next_data.shape

        image = QImage(self._next_data.flatten().tobytes(), y, x, QImage.Format_Grayscale8)

        if x != self._image_height or y != self._image_width:
            image = image.scaled(self._image_width, self._image_height, Qt.KeepAspectRatio)

        self._image.set_data(image)

        self._is_dirty = False

        self._fps_label.setText(f"{self._fps:.1f}")

    @Slot(ndarray, float)
    def refresh_image(self, data: ndarray, fps: float):
        self._next_data = data

        self._is_dirty = True

        if fps != self._fps:
            self._fps = fps
