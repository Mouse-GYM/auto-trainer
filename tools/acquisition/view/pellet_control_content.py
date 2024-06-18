from PySide6.QtGui import Qt
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QSpinBox, QLayout

from tools.acquisition.model.pellet_delivery_model import PelletDeliveryModel


def add_position(label: str, value: int, s_min: int, s_max: int) -> (QLayout, QSpinBox):
    position_layout = QHBoxLayout()
    position_layout.setContentsMargins(8, 8, 8, 8)
    position_layout.setSpacing(8)

    position_layout.addWidget(QLabel(label), 0)

    pos = QSpinBox()
    pos.setValue(value)
    pos.setMinimum(s_min)
    pos.setMaximum(s_max)
    pos.setWrapping(False)
    pos.setMinimumWidth(50)
    pos.setAlignment(Qt.AlignmentFlag.AlignRight)
    position_layout.addWidget(pos, 0)

    position_layout.addStretch(1)

    return position_layout, pos


class PelletControlContent(QWidget):
    def __init__(self, model: PelletDeliveryModel):
        super().__init__()

        self._model: PelletDeliveryModel = model

        layout = QHBoxLayout()

        p_layout, self._x_pos = add_position("X (mm):", self._model.x, -5, 5)
        self._x_pos.valueChanged.connect(self._update_x)
        layout.addLayout(p_layout)

        layout.addStretch(1)

        p_layout, self._y_pos = add_position("Y (mm):", self._model.y, -5, 5)
        self._y_pos.valueChanged.connect(self._update_y)
        layout.addLayout(p_layout)

        layout.addStretch(1)

        p_layout, self._z_pos = add_position("Z (mm):", self._model.z, -5, 5)
        self._z_pos.valueChanged.connect(self._update_z)
        layout.addLayout(p_layout)

        self.setLayout(layout)

        self.setEnabled(False)

        self._model.property_changed += self._model_property_changed

    def _update_x(self):
        self._model.set_x(self._x_pos.value())

    def _update_y(self):
        self._model.set_y(self._y_pos.value())

    def _update_z(self):
        self._model.set_z(self._z_pos.value())

    def _model_property_changed(self, name, value, _):
        if name == "x":
            self._x_pos.setValue(value)
        elif name == "y":
            self._y_pos.setValue(value)
        elif name == "z":
            self._z_pos.setValue(value)
