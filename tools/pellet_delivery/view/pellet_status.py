import math

from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QFormLayout

from autotrainer.core import Offset3DTuple
from autotrainer.pyside import CardWidget
from autotrainer.pyside.xyz_label import XYZQLabel
from tools.pellet_delivery.model.app_model import AppModel

_NO_UPDATES = "(no updates)"


def create_position_panel():
    layout = QFormLayout()
    layout.setHorizontalSpacing(8)
    x_y_z_device = XYZQLabel()
    layout.addRow("Triangle[motor] X/Y/Z (mm):", x_y_z_device)
    # ◈
    x_y_z_diamond = XYZQLabel()
    layout.addRow("Triangle[diamo] X/Y/Z (mm):", x_y_z_diamond)

    layout.setContentsMargins(8, 8, 8, 8)

    panel = CardWidget(title="Motor Location", content_layout=layout)

    return x_y_z_device, x_y_z_diamond, panel

def create_send_position_panel():
    layout = QFormLayout()
    layout.setHorizontalSpacing(8)

    x_y_z_device = XYZQLabel()
    layout.addRow("Send[motor] X/Y/Z (mm):", x_y_z_device)

    x_y_z_diamond = XYZQLabel()
    layout.addRow("Send[diamo] X/Y/Z (mm):", x_y_z_diamond)

    layout.setContentsMargins(8, 8, 8, 8)

    panel = CardWidget(title="Send Location", content_layout=layout)

    return x_y_z_device, x_y_z_diamond, panel


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

        self._xyz_device, self._xyz_diamond, panel = create_position_panel()
        layout.addWidget(panel)

        self._send_xyz_device, self._send_xyz_diamond, panel = create_send_position_panel()
        layout.addWidget(panel)

        self._load_arm, self._cover_arm, panel = create_servo_panel()
        layout.addWidget(panel)

        self.setLayout(layout)

    def _apply_diamond_triangle_compute(self, xyz: Offset3DTuple):
        diam_triangle_cfg = self._app_model.diamond_triangle_config
        if diam_triangle_cfg is None:
            return Offset3DTuple(math.nan, math.nan, math.nan)
        flips = Offset3DTuple([1 if v >= 0 else -1 for v in diam_triangle_cfg.measured_offset])
        flips *= self._app_model.motor_flips  # not sure
        return flips * (
            (xyz - diam_triangle_cfg.used_position) + diam_triangle_cfg.measured_offset
        )

    def _model_property_changed(self, name: str, value, _old_value):
        app_model = self._app_model
        if name in {'x', 'y', 'z'}:
            d = {name: value}
            self._xyz_device.update_coordinate(**d)
            cur_xyz = app_model.xyz.replace(**d)
            self._xyz_diamond.update_coordinate(self._apply_diamond_triangle_compute(cur_xyz))
        elif name in {'send_x', 'send_y', 'send_z'}:
            d = {name[-1]: value}
            self._send_xyz_device.update_coordinate(**d)
            cur_send_xyz = app_model.send_xyz.replace(**d)
            self._send_xyz_diamond.update_coordinate(self._apply_diamond_triangle_compute(cur_send_xyz))
        elif name == "load_arm":
            self._load_arm.setText(f"{round(value, 1)}")
        elif name == "cover_arm":
            self._cover_arm.setText(f"{round(value, 1)}")
        elif name == "is_connected":
            if not value:
                d = Offset3DTuple(math.nan, math.nan, math.nan)
                for xyz in self._xyz_device, self._xyz_diamond, self._send_xyz_device, self._send_xyz_diamond:
                    xyz.update_coordinate(d)
                self._load_arm.setText(_NO_UPDATES)
                self._cover_arm.setText(_NO_UPDATES)
