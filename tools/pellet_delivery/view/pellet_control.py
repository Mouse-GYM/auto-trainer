from PySide6.QtWidgets import QWidget, QGridLayout, QHBoxLayout, QPushButton, QLabel, QSpinBox, QLayout

from tools.pellet_delivery.model.app_model import AppModel


def add_position(label: str, s_min: int, s_max: int) -> (QLayout, QSpinBox):
    position_layout = QHBoxLayout()
    position_layout.setContentsMargins(8, 8, 8, 8)
    position_layout.setSpacing(8)

    position_layout.addWidget(QLabel(label), 0)

    pos = QSpinBox()
    pos.setMinimum(s_min)
    pos.setMaximum(s_max)
    pos.setWrapping(False)
    position_layout.addWidget(pos, 0)

    return position_layout, pos


class PelletControl(QWidget):
    def __init__(self, app_model: AppModel):
        super().__init__()

        self._app_model: AppModel = app_model

        layout = QGridLayout()

        b_layout = QHBoxLayout()
        b_layout.setSpacing(8)

        self._home_button = QPushButton("Home")
        self._home_button.clicked.connect(lambda: self._app_model.send_home())
        b_layout.addWidget(self._home_button)

        self._load_button = QPushButton("Load")
        self._load_button.clicked.connect(lambda: self._app_model.load_pellet())
        b_layout.addWidget(self._load_button)

        self._send_button = QPushButton("Send")
        self._send_button.clicked.connect(lambda: self._app_model.send_pellet())
        b_layout.addWidget(self._send_button)

        self._release_button = QPushButton("Release")
        self._release_button.clicked.connect(lambda: self._app_model.release_pellet())
        b_layout.addWidget(self._release_button)

        layout.addLayout(b_layout, 0, 0, 1, 3)

        p_layout, self._x_pos = add_position("X (mm):", -5, 5)
        self._x_pos.valueChanged.connect(self._update_x)
        layout.addLayout(p_layout, 1, 0)

        p_layout, self._y_pos = add_position("Y (mm):", -5, 5)
        self._y_pos.valueChanged.connect(self._update_y)
        layout.addLayout(p_layout, 1, 1)

        p_layout, self._z_pos = add_position("Z (mm):", -5, 5)
        self._z_pos.valueChanged.connect(self._update_z)
        layout.addLayout(p_layout, 1, 2)

        self.setLayout(layout)

        self.setEnabled(False)

    def _update_x(self):
        self._app_model.set_x(self._x_pos.value())

    def _update_y(self):
        self._app_model.set_y(self._y_pos.value())

    def _update_z(self):
        self._app_model.set_z(self._z_pos.value())
