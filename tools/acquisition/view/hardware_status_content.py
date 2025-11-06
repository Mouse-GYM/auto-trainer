from functools import partial

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QVBoxLayout, QLabel, QHBoxLayout, QWidget, QGridLayout, QFormLayout, QSizePolicy

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
        # self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)

        self._model = message_handler

        self._card_widget = CardWidget(title="Hardware Status")

        self._model.property_changed += self._model_property_changed

        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        layout = QGridLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(4)
        content_layout.addLayout(layout)

        cur_row = cur_col = 0

        label = QLabel("<b>Tunnel:</b>")
        layout.addWidget(label, cur_row, cur_col)
        cur_row += 1

        layout.addWidget(QLabel("Head magnet (%):"), cur_row, cur_col)
        self._head_magnet = QLabel("(no updates)")
        layout.addWidget(self._head_magnet, cur_row, cur_col + 1)
        cur_row += 1

        #

        label = QLabel("<b>Pellet:</b>")
        label.setContentsMargins(0, 4, 0, 0)
        layout.addWidget(label, cur_row, cur_col)
        cur_row += 1

        layout.addWidget(QLabel("XYZ (mm):"), cur_row, cur_col)
        self._pellet_xyz = XYZQLabel()
        layout.addWidget(self._pellet_xyz, cur_row, cur_col + 1)
        cur_row += 1

        layout.addWidget(QLabel("Send XYZ (mm):"), cur_row, cur_col)
        self._send_pellet_xyz = XYZQLabel()
        layout.addWidget(self._send_pellet_xyz, cur_row, cur_col + 1)
        cur_row += 1

        layout.addWidget(QLabel("Load Arm (\u00b0):"), cur_row, cur_col)
        self._load_arm = QLabel("(no updates)")
        layout.addWidget(self._load_arm, cur_row, cur_col + 1)
        cur_row += 1

        layout.addWidget(QLabel("Cover Arm (\u00b0):"), cur_row, cur_col)
        self._cover_arm = QLabel("(no updates)")
        layout.addWidget(self._cover_arm, cur_row, cur_col + 1)

        content = QWidget()
        content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        content.setContentsMargins(0, 4, 0, 4)
        content.setLayout(content_layout)

        self._card_widget.setContentWidget(content)

        #
        # Final layout
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._card_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

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
