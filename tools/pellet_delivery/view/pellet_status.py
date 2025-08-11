from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QFormLayout

from autotrainer.pyside import CardWidget
from tools.pellet_delivery.model.app_model import AppModel

_NO_UPDATES = "(no updates)"


def create_position_panel():
    layout = QFormLayout()
    layout.setHorizontalSpacing(8)
    x = QLabel(_NO_UPDATES)
    y = QLabel(_NO_UPDATES)
    z = QLabel(_NO_UPDATES)

    layout.addRow("X (mm):", x)
    layout.addRow("Y (mm):", y)
    layout.addRow("Z (mm):", z)

    layout.setContentsMargins(8, 8, 8, 8)

    panel = CardWidget(title="Motor Location", content_layout=layout)

    return x, y, z, panel

def create_send_position_panel():
    layout = QFormLayout()
    layout.setHorizontalSpacing(8)
    x = QLabel(_NO_UPDATES)
    y = QLabel(_NO_UPDATES)
    z = QLabel(_NO_UPDATES)

    layout.addRow("X (mm):", x)
    layout.addRow("Y (mm):", y)
    layout.addRow("Z (mm):", z)

    layout.setContentsMargins(8, 8, 8, 8)

    panel = CardWidget(title="Send Location", content_layout=layout)

    return x, y, z, panel


def create_servo_panel():
    layout = QFormLayout()
    layout.setHorizontalSpacing(8)

    load_arm = QLabel(_NO_UPDATES)
    cover_arm = QLabel(_NO_UPDATES)

    layout.addRow("Load Arm (\u00b0):", load_arm)
    layout.addRow("Cover Arm (\u00b0):", cover_arm)

    layout.setContentsMargins(8, 8, 8, 8)

    panel = CardWidget(title="Servos", content_layout=layout)

    return load_arm, cover_arm, panel


class PelletStatus(QWidget):
    def __init__(self, app_model: AppModel):
        super().__init__()

        self._app_model: AppModel = app_model

        self._app_model.property_changed += self._model_property_changed

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        self._x_device, self._y_device, self._z_device, panel = create_position_panel()
        layout.addWidget(panel)

        self._send_x_device, self._send_y_device, self._send_z_device, panel = create_send_position_panel()
        layout.addWidget(panel)

        self._load_arm, self._cover_arm, panel = create_servo_panel()
        layout.addWidget(panel)

        self.setLayout(layout)

    def _model_property_changed(self, name: str, value, _old_value):
        if name == "x":
            self._x_device.setText(f"{round(value, 2)}")
        elif name == "y":
            self._y_device.setText(f"{round(value, 2)}")
        elif name == "z":
            self._z_device.setText(f"{round(value, 2)}")
        elif name == "send_x":
            self._send_x_device.setText(f"{round(value, 2)}")
        elif name == "send_y":
            self._send_y_device.setText(f"{round(value, 2)}")
        elif name == "send_z":
            self._send_z_device.setText(f"{round(value, 2)}")
        elif name == "load_arm":
            self._load_arm.setText(f"{round(value, 1)}")
        elif name == "cover_arm":
            self._cover_arm.setText(f"{round(value, 1)}")
        elif name == "is_connected":
            if not value:
                self._x_device.setText(_NO_UPDATES)
                self._y_device.setText(_NO_UPDATES)
                self._z_device.setText(_NO_UPDATES)
                self._load_arm.setText(_NO_UPDATES)
                self._cover_arm.setText(_NO_UPDATES)
