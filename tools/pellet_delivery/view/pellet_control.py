from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel, QSpinBox, \
    QLayout, QVBoxLayout, QFileDialog, QFrame

import qtawesome as qta

from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.message import Motor
from autotrainer.device import is_servo
from autotrainer.model import HardwareVersion, EnvironmentProvider
from autotrainer.pyside import ATSeparator

from tools.pellet_delivery.model.app_model import AppModel
from tools.view.basic_panel import create_panel
from tools.view.motor_config_dialog import MotorConfigDialog


logger = get_verbose_logger(__name__)

_NO_UPDATES = "(no updates)"

_MIN_CONTROL_BUTTON_WIDTH = 120


def add_position(label: str, s_min: int, s_max: int) -> (QLayout, QSpinBox):
    position_layout = QHBoxLayout()
    position_layout.setContentsMargins(8, 8, 8, 8)
    position_layout.setSpacing(8)

    position_layout.addWidget(QLabel(label), 0)

    pos = QSpinBox()
    pos.setMinimumWidth(40)
    pos.setMinimum(s_min)
    pos.setMaximum(s_max)
    pos.setWrapping(False)
    position_layout.addWidget(pos, 0)

    moveButton = QPushButton("Move")
    position_layout.addWidget(moveButton, 0)

    setButton = QPushButton("Set")
    position_layout.addWidget(setButton, 0)

    return position_layout, pos, moveButton, setButton


class PelletControl(QWidget):
    def __init__(self, app_model: AppModel):
        super().__init__()

        self._app_model: AppModel = app_model

        self._config_dialog = None

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

        self._homing_button = QPushButton("Homing")
        self._homing_button.setMinimumWidth(_MIN_CONTROL_BUTTON_WIDTH)
        self._homing_button.clicked.connect(self._app_model.send_homing)
        b_layout.addWidget(self._homing_button)

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

        b_layout.addStretch(1)

        self._move_file_button = QPushButton("")
        folder_icon = qta.icon('fa5s.folder-open')
        self._move_file_button.setIcon(folder_icon)
        self._move_file_button.clicked.connect(lambda: self._load_move_file())
        if EnvironmentProvider.hardware_version() != HardwareVersion.ANSHUTZ:
            b_layout.addWidget(self._move_file_button)

        self._config_button = QPushButton("")
        gear_icon = qta.icon('fa5s.cog')  # Font Awesome 5 Solid cog icon
        self._config_button.setIcon(gear_icon)
        self._config_button.clicked.connect(lambda: self._update_config())
        if EnvironmentProvider.hardware_version() != HardwareVersion.ANSHUTZ:
            b_layout.addWidget(self._config_button)

        return b_layout

    def _create_move_layout(self):
        s_layout = QHBoxLayout()
        s_layout.setContentsMargins(2, 2, 2, 2)

        is_legacy = EnvironmentProvider.hardware_version() == HardwareVersion.ANSHUTZ

        p_layout, self._x_pos, moveButton, setButton = add_position("X (mm):", -10, 10)
        moveButton.clicked.connect(lambda: self._move_x())
        setButton.clicked.connect(lambda: self._set_x())
        s_layout.addLayout(p_layout)

        
        if is_legacy:
            moveButton.setVisible(False)

        s_layout.addStretch(1)

        line = QFrame()
        line.setFrameShape(QFrame.VLine)
        line.setFrameShadow(QFrame.Sunken)
        s_layout.addWidget(line)

        s_layout.addStretch(1)

        p_layout, self._y_pos, moveButton, setButton = add_position("Y (mm):", -10, 10)
        moveButton.clicked.connect(lambda: self._move_y())
        setButton.clicked.connect(lambda: self._set_y())
        s_layout.addLayout(p_layout)

        
        if is_legacy:
            moveButton.setVisible(False)

        s_layout.addStretch(1)

        line = QFrame()
        line.setFrameShape(QFrame.VLine)
        line.setFrameShadow(QFrame.Sunken)
        s_layout.addWidget(line)

        s_layout.addStretch(1)

        p_layout, self._z_pos, moveButton, setButton = add_position("Z (mm):", -10, 10)
        moveButton.clicked.connect(lambda: self._move_z())
        setButton.clicked.connect(lambda: self._set_z())
        s_layout.addLayout(p_layout)

        
        if is_legacy:
            moveButton.setVisible(False)

        return s_layout

    def _set_x(self):
        self._app_model.set_x(self._x_pos.value())

    def _set_y(self):
        self._app_model.set_y(self._y_pos.value())

    def _set_z(self):
        self._app_model.set_z(self._z_pos.value())

    def _move_x(self):
        self._app_model.move_x(self._x_pos.value())

    def _move_y(self):
        self._app_model.move_y(self._y_pos.value())

    def _move_z(self):
        self._app_model.move_z(self._z_pos.value())

    def _model_property_changed(self, name: str, value, _old_value):
        if name == "travel_limits":
            logger.debug("got & applying travel_limits: %s", value)
            self._x_pos.setMinimum(value["x"][0])
            self._x_pos.setMaximum(value["x"][1])
            self._y_pos.setMinimum(value["y"][0])
            self._y_pos.setMaximum(value["y"][1])
            self._z_pos.setMinimum(value["z"][0])
            self._z_pos.setMaximum(value["z"][1])
        elif name == "config":
            if self._config_dialog is not None:
                if is_servo(value.motor):
                    self._config_dialog.update_servo_config(value)
                else:
                    self._config_dialog.update_stepper_config(value)

    def _update_config(self):
        self._config_dialog = MotorConfigDialog(self)
        self._config_dialog.motor_selected.connect(self._on_motor_selected)
        self._config_dialog.accepted.connect(self._on_config_accepted)
        self._config_dialog.rejected.connect(lambda: setattr(self, '_config_dialog', None))

        self._config_dialog.setModal(True)
        self._config_dialog.show()

    def _on_config_accepted(self):
        if self._config_dialog.config is not None:
            self._app_model.set_config((self._config_dialog.config.motor,
                                        self._config_dialog.config))

        self._config_dialog = None

    def _on_motor_selected(self, motor: Motor):
        self._app_model.get_config(motor)

    def _load_move_file(self):
        dialog = QFileDialog(self)
        dialog.setWindowTitle("Open File")
        dialog.setFileMode(QFileDialog.ExistingFile)  # Allow only one file to be selected

        # Optionally set filters for file types
        dialog.setNameFilter("All Files (*)")

        # Show the dialog and wait for user's response
        if dialog.exec_():
            # Get the selected file path(s) - will be a list
            selected_files = dialog.selectedFiles()
            # Return the first (and likely only) file

            self._app_model.load_move_file(selected_files[0])
