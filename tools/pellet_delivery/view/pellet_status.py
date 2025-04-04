from PySide6.QtWidgets import QWidget, QGridLayout, QHBoxLayout, QPushButton, QLabel, QSpinBox, QLayout, QVBoxLayout, \
    QFormLayout

from autotrainer.pyside import CardWidget
from tools.pellet_delivery.model.app_model import AppModel

_NO_UPDATES = "(no updates)"


class PelletStatus(QWidget):
    def __init__(self, app_model: AppModel):
        super().__init__()

        self._app_model: AppModel = app_model

        self._app_model.property_changed += self._model_property_changed

        self._x_device = QLabel(_NO_UPDATES)
        self._y_device = QLabel(_NO_UPDATES)
        self._z_device = QLabel(_NO_UPDATES)

        self._load_arm = QLabel(_NO_UPDATES)
        self._cover_arm = QLabel(_NO_UPDATES)

        layout = QGridLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._create_motor_panel(self._x_device, self._y_device, self._z_device), 1, 0)
        layout.addWidget(self._create_servo_panel(self._load_arm, self._cover_arm), 1, 1)
        self.setLayout(layout)

    # noinspection PyMethodMayBeStatic
    def _create_motor_panel(self, x, y, z) -> QWidget:
        panel = CardWidget(background_color="#00b6de")

        layout = QFormLayout()
        layout.addRow("X (mm):", x)
        layout.addRow("Y (mm):", y)
        layout.addRow("Z (mm):", z)

        content = QWidget()
        content.setLayout(layout)
        panel.setContentWidget(content)

        header = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("Motors")
        title.setStyleSheet("font-weight: bold; color: white")
        layout.addWidget(title)
        layout.addStretch(1)

        header.setLayout(layout)

        panel.header.setContent(header)

        return panel

    # noinspection PyMethodMayBeStatic
    def _create_servo_panel(self, load, cover) -> QWidget:
        panel = CardWidget(background_color="#00b6de")

        layout = QFormLayout()
        layout.addRow("Load Arm (\u00b0):", load)
        layout.addRow("Cover Arm (\u00b0):", cover)

        content = QWidget()
        content.setLayout(layout)
        panel.setContentWidget(content)

        header = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("Servos")
        title.setStyleSheet("font-weight: bold; color: white")
        layout.addWidget(title)
        layout.addStretch(1)

        header.setLayout(layout)

        panel.header.setContent(header)

        return panel

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
