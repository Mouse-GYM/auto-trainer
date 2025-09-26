from functools import partial

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QVBoxLayout, QLabel, QHBoxLayout, QWidget, QGridLayout, QFormLayout

from autotrainer.core import MessageHandler
from autotrainer.pyside import CardWidget
from autotrainer.pyside.xyz_label import XYZQLabel

from tools.acquisition.view.content_widget import ContentWidget


class HardwareStatusContent(ContentWidget):
    head_magnet_changed = Signal(float, name="head_magnet_changed")
    pellet_x_changed = Signal(float, name="pellet_x_changed")
    pellet_y_changed = Signal(float, name="pellet_y_changed")
    pellet_z_changed = Signal(float, name="pellet_z_changed")
    send_x_changed = Signal(float, name="send_x_changed")
    send_y_changed = Signal(float, name="send_y_changed")
    send_z_changed = Signal(float, name="send_z_changed")
    load_arm_changed = Signal(float, name="load_arm_changed")
    cover_arm_changed = Signal(float, name="cover_arm_changed")

    def __init__(self, message_handler: MessageHandler):
        super().__init__()

        self._model = message_handler

        self._card_widget = CardWidget(title="Hardware Status")

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

        form_layout = QFormLayout(None)
        form_layout.setHorizontalSpacing(8)
        form_layout.setVerticalSpacing(4)

        self._head_magnet = QLabel("(no updates)")
        form_layout.addRow("Head magnet (%):", self._head_magnet)

        layout.addLayout(form_layout, 1, 0)

        form_layout = QFormLayout(None)
        form_layout.setHorizontalSpacing(8)
        form_layout.setVerticalSpacing(4)

        self._pellet_xyz = XYZQLabel()
        form_layout.addRow("XYZ (mm) :", self._pellet_xyz)
        self._send_pellet_xyz = XYZQLabel()
        form_layout.addRow("Send XYZ (mm) :", self._send_pellet_xyz)
        #
        self._load_arm = QLabel("(no updates)")
        form_layout.addRow("Load Arm (\u00b0):", self._load_arm)
        self._cover_arm = QLabel("(no updates)")
        form_layout.addRow("Cover Arm (\u00b0):", self._cover_arm)

        layout.addLayout(form_layout, 1, 2)

        layout.setRowStretch(2, 1)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(3, 1)

        self._card_widget.setContentLayout(layout)

        # Final layout
        layout = QVBoxLayout()
        layout.addWidget(self._card_widget)
        self.setLayout(layout)

        def xyz_update(xyz_label: XYZQLabel, coord, value):
            xyz_label.update_coordinate(**{coord: value})

        self.head_magnet_changed.connect(lambda x: self._head_magnet.setText(str(round(x, 1))))
        self.pellet_x_changed.connect(partial(xyz_update, self._pellet_xyz, "x"))
        self.pellet_y_changed.connect(partial(xyz_update, self._pellet_xyz, "y"))
        self.pellet_z_changed.connect(partial(xyz_update, self._pellet_xyz, "z"))
        self.send_x_changed.connect(partial(xyz_update, self._send_pellet_xyz, "x"))
        self.send_y_changed.connect(partial(xyz_update, self._send_pellet_xyz, "y"))
        self.send_z_changed.connect(partial(xyz_update, self._send_pellet_xyz, "z"))
        self.load_arm_changed.connect(lambda x: self._load_arm.setText(str(round(x, 1))))
        self.cover_arm_changed.connect(lambda x: self._cover_arm.setText(str(round(x, 1))))

    def _model_property_changed(self, property_name: str, value, _):
        # If any of the values may be coming from a different thread (e.g., the device), a signal is generally needed
        # rather than direct set/update.
        if property_name == MessageHandler.HEAD_MAGNET_INTENSITY_PROPERTY:
            self.head_magnet_changed.emit(value)
        elif property_name == MessageHandler.STEPPER_X_PROPERTY:
            self.pellet_x_changed.emit(value.position)
            self.send_x_changed.emit(value.send_position)
        elif property_name == MessageHandler.STEPPER_Y_PROPERTY:
            self.pellet_y_changed.emit(value.position)
            self.send_y_changed.emit(value.send_position)
        elif property_name == MessageHandler.STEPPER_Z_PROPERTY:
            self.pellet_z_changed.emit(value.position)
            self.send_z_changed.emit(value.send_position)
        elif property_name == MessageHandler.LOAD_ARM_ANGLE_PROPERTY:
            self.load_arm_changed.emit(value)
        elif property_name == MessageHandler.COVER_ARM_ANGLE_PROPERTY:
            self.cover_arm_changed.emit(value)
