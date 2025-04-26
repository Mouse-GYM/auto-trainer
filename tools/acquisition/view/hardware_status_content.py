from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QVBoxLayout, QLabel, QHBoxLayout, QWidget, QGridLayout, QFormLayout

from autotrainer.core import MessageHandler
from autotrainer.pyside import CardWidget

from tools.acquisition.view.content_widget import ContentWidget


class HardwareStatusContent(ContentWidget):
    head_magnet_changed = Signal(float, name="head_magnet_changed")
    pellet_x_changed = Signal(float, name="pellet_x_changed")
    pellet_y_changed = Signal(float, name="pellet_y_changed")
    pellet_z_changed = Signal(float, name="pellet_z_changed")
    load_arm_changed = Signal(float, name="load_arm_changed")
    cover_arm_changed = Signal(float, name="cover_arm_changed")

    def __init__(self, message_handler: MessageHandler):
        super().__init__()

        self._model = message_handler

        self._card_widget = CardWidget(None)

        self._model.property_changed += self._model_property_changed

        layout = QGridLayout(None)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setHorizontalSpacing(16)

        label = QLabel("Tunnel")
        label.setStyleSheet("font-weight: bold")
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label, 0, 0)
        label = QLabel("Pellet")
        label.setStyleSheet("font-weight: bold")
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label, 0, 2)
        label = QLabel("Other")
        label.setStyleSheet("font-weight: bold")
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label, 0, 4)

        form_layout = QFormLayout(None)
        form_layout.setHorizontalSpacing(8)
        form_layout.setVerticalSpacing(4)

        self._head_magnet = QLabel("(no updates)")
        form_layout.addRow("Head magnet intensity (%):", self._head_magnet)

        layout.addLayout(form_layout, 1, 0)

        form_layout = QFormLayout(None)
        form_layout.setHorizontalSpacing(8)
        form_layout.setVerticalSpacing(4)

        self._pellet_x = QLabel("(no updates)")
        form_layout.addRow("X (mm):", self._pellet_x)
        self._pellet_y = QLabel("(no updates)")
        form_layout.addRow("X (mm):", self._pellet_y)
        self._pellet_z = QLabel("(no updates)")
        form_layout.addRow("z (mm):", self._pellet_z)
        self._load_arm = QLabel("(no updates)")
        form_layout.addRow("Load Arm (\u00b0):", self._load_arm)
        self._cover_arm = QLabel("(no updates)")
        form_layout.addRow("Cover Arm (\u00b0):", self._cover_arm)

        layout.addLayout(form_layout, 1, 2)

        layout.setRowStretch(2, 1)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(3, 1)

        self._card_widget.setContentLayout(layout)

        # Header
        self._header = QWidget(None)
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = QLabel("Hardware Status")
        title.setStyleSheet("font-weight: bold")
        layout.addWidget(title)

        layout.addStretch(1)

        self._header.setLayout(layout)

        self._card_widget.header.setContent(self._header)

        # Final layout
        layout = QVBoxLayout()
        layout.addWidget(self._card_widget)
        self.setLayout(layout)

        self.head_magnet_changed.connect(lambda x: self._head_magnet.setText(str(round(x, 1))))
        self.pellet_x_changed.connect(lambda x: self._pellet_x.setText(str(round(x, 1))))
        self.pellet_y_changed.connect(lambda x: self._pellet_y.setText(str(round(x, 1))))
        self.pellet_z_changed.connect(lambda x: self._pellet_z.setText(str(round(x, 1))))
        self.load_arm_changed.connect(lambda x: self._load_arm.setText(str(round(x, 1))))
        self.cover_arm_changed.connect(lambda x: self._cover_arm.setText(str(round(x, 1))))

    def _model_property_changed(self, property_name: str, value, _):
        # If any of the values may be coming from a different thread (e.g., the device), a signal is generally needed
        # rather than direct set/update.
        if property_name == MessageHandler.HEAD_MAGNET_INTENSITY_PROPERTY:
            self.head_magnet_changed.emit(value)
        elif property_name == MessageHandler.DEVICE_X_PROPERTY:
            self.pellet_x_changed.emit(value)
        elif property_name == MessageHandler.DEVICE_Y_PROPERTY:
            self.pellet_y_changed.emit(value)
        elif property_name == MessageHandler.DEVICE_Z_PROPERTY:
            self.pellet_z_changed.emit(value)
        elif property_name == MessageHandler.LOAD_ARM_ANGLE_PROPERTY:
            self.load_arm_changed.emit(value)
        elif property_name == MessageHandler.COVER_ARM_ANGLE_PROPERTY:
            self.cover_arm_changed.emit(value)
