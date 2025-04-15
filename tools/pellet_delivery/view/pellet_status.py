from PySide6.QtWidgets import QWidget, QGridLayout, QHBoxLayout, QPushButton, QLabel, QSpinBox, \
    QLayout, QVBoxLayout, \
    QFormLayout

from autotrainer.pyside import CardWidget
from tools.pellet_delivery.model.app_model import AppModel
from tools.view.basic_panel import create_panel

_NO_UPDATES = "(no updates)"


def create_motor_panel():
    layout = QFormLayout()
    x = QLabel(_NO_UPDATES)
    y = QLabel(_NO_UPDATES)
    z = QLabel(_NO_UPDATES)

    layout.addRow("X (mm):", x)
    layout.addRow("Y (mm):", y)
    layout.addRow("Z (mm):", z)

    return x, y, z, create_panel("Motors", layout)


def create_servo_panel():
    layout = QFormLayout()

    load_arm = QLabel(_NO_UPDATES)
    cover_arm = QLabel(_NO_UPDATES)

    layout.addRow("Load Arm (\u00b0):", load_arm)
    layout.addRow("Cover Arm (\u00b0):", cover_arm)

    return load_arm, cover_arm, create_panel("Servos", layout)


class PelletStatus(QWidget):
    def __init__(self, app_model: AppModel):
        super().__init__()

        self._app_model: AppModel = app_model

        self._app_model.property_changed += self._model_property_changed

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        self._x_device, self._y_device, self._z_device, panel = create_motor_panel()
        layout.addWidget(panel)

        self._load_arm, self._cover_arm, panel = create_servo_panel()
        layout.addWidget(panel)

        self.setLayout(layout)

    def _model_property_changed(self, name: str, value, _old_value):
        if name == "x":
            self._x_device.setText(f"{round(value, 3)}")
        elif name == "y":
            self._y_device.setText(f"{round(value, 3)}")
        elif name == "z":
            self._z_device.setText(f"{round(value, 3)}")
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
