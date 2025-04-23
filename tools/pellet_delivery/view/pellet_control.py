from PySide6.QtWidgets import QWidget, QGridLayout, QHBoxLayout, QPushButton, QLabel, QSpinBox, \
    QLayout, QVBoxLayout, \
    QFormLayout

from autotrainer.pyside import ATSeparator
from tools.pellet_delivery.model.app_model import AppModel
from tools.view.basic_panel import create_panel

_NO_UPDATES = "(no updates)"

_MIN_CONTROL_BUTTON_WIDTH = 120


def add_position(label: str, s_min: int, s_max: int) -> (QLayout, QSpinBox):
    position_layout = QHBoxLayout()
    position_layout.setContentsMargins(8, 8, 8, 8)
    position_layout.setSpacing(8)

    position_layout.addWidget(QLabel(label), 0)

    pos = QSpinBox()
    pos.setMinimumWidth(140)
    pos.setMinimum(s_min)
    pos.setMaximum(s_max)
    pos.setWrapping(False)
    position_layout.addWidget(pos, 0)

    return position_layout, pos


class PelletControl(QWidget):
    def __init__(self, app_model: AppModel):
        super().__init__()

        self._app_model: AppModel = app_model

        self._app_model.property_changed += self._model_property_changed

        layout = QVBoxLayout()
        panel = create_panel("Control", layout)
        layout.addLayout(self._create_button_layout())
        layout.addWidget(ATSeparator("#dedede"))
        layout.addLayout(self._create_move_layout())

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(panel)

        self.setLayout(layout)
        self.setEnabled(False)

    def _create_button_layout(self):
        b_layout = QHBoxLayout()
        b_layout.setContentsMargins(2, 2, 2, 2)
        b_layout.setSpacing(8)

        self._home_button = QPushButton("Home")
        self._home_button.setMinimumWidth(_MIN_CONTROL_BUTTON_WIDTH)
        self._home_button.clicked.connect(lambda: self._app_model.send_home())
        b_layout.addWidget(self._home_button)

        b_layout.addStretch(1)

        self._load_button = QPushButton("Load")
        self._load_button.setMinimumWidth(_MIN_CONTROL_BUTTON_WIDTH)
        self._load_button.clicked.connect(lambda: self._app_model.load_pellet())
        b_layout.addWidget(self._load_button)

        self._send_button = QPushButton("Send")
        self._send_button.setMinimumWidth(_MIN_CONTROL_BUTTON_WIDTH)
        self._send_button.clicked.connect(lambda: self._app_model.send_pellet())
        b_layout.addWidget(self._send_button)

        b_layout.addStretch(1)

        self._release_button = QPushButton("Release")
        self._release_button.setMinimumWidth(_MIN_CONTROL_BUTTON_WIDTH)
        self._release_button.clicked.connect(lambda: self._app_model.release_pellet())
        b_layout.addWidget(self._release_button)

        self._cover_button = QPushButton("Cover")
        self._cover_button.setMinimumWidth(_MIN_CONTROL_BUTTON_WIDTH)
        self._cover_button.clicked.connect(lambda: self._app_model.cover_pellet())
        b_layout.addWidget(self._cover_button)

        return b_layout

    def _create_move_layout(self):
        s_layout = QHBoxLayout()
        s_layout.setContentsMargins(2, 2, 2, 2)

        p_layout, self._x_pos = add_position("X (mm):", -10, 10)
        self._x_pos.valueChanged.connect(self._update_x)
        s_layout.addLayout(p_layout)

        s_layout.addStretch(1)

        p_layout, self._y_pos = add_position("Y (mm):", -10, 10)
        self._y_pos.valueChanged.connect(self._update_y)
        s_layout.addLayout(p_layout)

        s_layout.addStretch(1)

        p_layout, self._z_pos = add_position("Z (mm):", -10, 10)
        self._z_pos.valueChanged.connect(self._update_z)
        s_layout.addLayout(p_layout)

        return s_layout

    def _update_x(self):
        self._app_model.set_x(self._x_pos.value())

    def _update_y(self):
        self._app_model.set_y(self._y_pos.value())

    def _update_z(self):
        self._app_model.set_z(self._z_pos.value())

    def _model_property_changed(self, name: str, value, _old_value):
        if name == "travel_limits":
            self._x_pos.setMinimum(value["x"][0])
            self._x_pos.setMaximum(value["x"][1])
            self._y_pos.setMinimum(value["y"][0])
            self._y_pos.setMaximum(value["y"][1])
            self._z_pos.setMinimum(value["z"][0])
            self._z_pos.setMaximum(value["z"][1])
