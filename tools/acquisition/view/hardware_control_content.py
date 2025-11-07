import logging
import typing

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (QLabel, QSpinBox, QWidget, QPushButton, QVBoxLayout, QHBoxLayout, QGridLayout,
                               QFormLayout, QStackedLayout, QSizePolicy)

from autotrainer.core import AnimalSubject
from autotrainer.model import EnvironmentProvider, HardwareVersion
from autotrainer.pyside import CardWidget
from tools.acquisition.model.hardware_model import HardwareModel

from tools.acquisition.view.content_widget import ContentWidget

logger = logging.getLogger(__name__)

# TODO: This is just to see if the behavior is correct.  They should end up somewhere that any application or script can
#  access.
_anshutz_travel_limits = {
    "x": (-10, 10),
    "y": (-10, 10),
    "z": (-10, 10),
}

_alogus_travel_limits = {
    "x": (0, 35),
    "y": (0, 35),
    "z": (0, 35),
}


class HardwareControlContent(ContentWidget):
    position_changed = Signal(int, name="position_changed")
    command_changed = Signal(str, name="command_changed")

    def __init__(self, model: HardwareModel):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)

        self._model = model

        # Header
        layout = QHBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.setSpacing(16)

        layout.addWidget(QLabel("Tunnel:"))
        self._tunnel_version = QLabel("(unknown version)")
        layout.addWidget(self._tunnel_version)

        layout.addWidget(QLabel("Pellet:"))
        self._pellet_version = QLabel("(unknown version)")
        layout.addWidget(self._pellet_version)

        self._card_widget = CardWidget(title="Hardware Control", header_right_layout=layout)

        if EnvironmentProvider.hardware_version() == HardwareVersion.ANSHUTZ:
            self._travel_limits = _anshutz_travel_limits
        else:
            self._travel_limits = _alogus_travel_limits

        layout = QGridLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        label = QLabel("<b>Tunnel</b>")
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label, 0, 0)
        label = QLabel("<b>Pellet Release Location</b>")
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label, 0, 2)
        label = QLabel("<b>Compound Move</b>")
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label, 0, 4)

        form_layout = QFormLayout()
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        form_layout.setHorizontalSpacing(8)
        form_layout.setVerticalSpacing(4)

        self._position = QSpinBox()
        self._position.setValue(0)
        self._position.setMaximum(100)
        self._position.setWrapping(False)
        self._magnet_move_button = QPushButton("Move")
        self._magnet_move_button.clicked.connect(
            lambda: self._model.update_head_magnet_intensity(self._position.value()))
        right_layout = QHBoxLayout()
        right_layout.setSpacing(4)
        right_layout.addWidget(self._position)
        right_layout.addWidget(self._magnet_move_button)
        form_layout.addRow("Head magnet intensity (%):", right_layout)

        self._tare_button = QPushButton("Tare")
        self._tare_button.setEnabled(False)
        self._tare_button.clicked.connect(self._model.tare_load_cell)
        form_layout.addRow(QLabel("Load cell:"), self._tare_button)

        layout.addLayout(form_layout, 1, 0)

        form_layout = QFormLayout()
        form_layout.setHorizontalSpacing(8)
        form_layout.setVerticalSpacing(4)

        self._x_pos = QSpinBox()
        self._x_pos.setValue(0)
        self._x_pos.setMinimum(self._travel_limits["x"][0])
        self._x_pos.setMaximum(self._travel_limits["x"][1])
        self._x_pos.setWrapping(False)
        self._x_pos.setMinimumWidth(50)
        self._x_pos.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._x_move_button = QPushButton("Set")
        self._x_move_button.clicked.connect(lambda: self._model.set_x(self._x_pos.value()))
        right_layout = QHBoxLayout()
        right_layout.setSpacing(4)
        right_layout.addWidget(self._x_pos)
        right_layout.addWidget(self._x_move_button)
        form_layout.addRow(QLabel("Pellet X (mm):"), right_layout)

        self._y_pos = QSpinBox(None)
        self._y_pos.setValue(0)
        self._y_pos.setMinimum(self._travel_limits["y"][0])
        self._y_pos.setMaximum(self._travel_limits["y"][1])
        self._y_pos.setWrapping(False)
        self._y_pos.setMinimumWidth(50)
        self._y_pos.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._y_move_button = QPushButton("Set")
        self._y_move_button.clicked.connect(lambda: self._model.set_y(self._y_pos.value()))
        right_layout = QHBoxLayout()
        right_layout.setSpacing(4)
        right_layout.addWidget(self._y_pos)
        right_layout.addWidget(self._y_move_button)
        form_layout.addRow(QLabel("Pellet Y (mm):"), right_layout)

        self._z_pos = QSpinBox(None)
        self._z_pos.setValue(0)
        self._z_pos.setMinimum(self._travel_limits["z"][0])
        self._z_pos.setMaximum(self._travel_limits["z"][1])
        self._z_pos.setWrapping(False)
        self._z_pos.setMinimumWidth(50)
        self._z_pos.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._z_move_button = QPushButton("Set")
        self._z_move_button.clicked.connect(lambda: self._model.set_z(self._z_pos.value()))
        right_layout = QHBoxLayout()
        right_layout.setSpacing(4)
        right_layout.addWidget(self._z_pos)
        right_layout.addWidget(self._z_move_button)
        form_layout.addRow(QLabel("Pellet Z (mm):"), right_layout)

        layout.addLayout(form_layout, 1, 2)

        button_layout = QVBoxLayout()
        button_layout.setSpacing(4)
        self._home_button = QPushButton("Home")
        self._home_button.clicked.connect(lambda: self._model.send_home())
        button_layout.addWidget(self._home_button)
        self._load_button = QPushButton("Load")
        self._load_button.clicked.connect(lambda: self._model.load_pellet())
        button_layout.addWidget(self._load_button)
        self._send_button = QPushButton("Send")
        self._send_button.clicked.connect(lambda: self._model.send_pellet())
        button_layout.addWidget(self._send_button)
        self._release_button = QPushButton("Release")
        self._release_button.clicked.connect(lambda: self._model.release_pellet())
        button_layout.addWidget(self._release_button)
        self._cover_button = QPushButton("Cover")
        self._cover_button.clicked.connect(lambda: self._model.cover_pellet())
        button_layout.addWidget(self._cover_button)

        layout.addLayout(button_layout, 1, 4)
        self._card_widget.setContentLayout(layout)
        self._card_widget.setSizePolicy(self.sizePolicy())

        # Footer
        self._basic_footer = QWidget()

        layout = QHBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Command in progress:"))
        self._command_label = QLabel("None")
        layout.addWidget(self._command_label)

        self._basic_footer.setLayout(layout)

        self._stack_layout = QStackedLayout()
        self._stack_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._stack_layout.addWidget(self._basic_footer)

        widget = QWidget()
        widget.setLayout(self._stack_layout)

        self._card_widget.footer.setContent(widget)

        # Final layout
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._card_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.setLayout(layout)

        self.setEnabled(False)

        self.command_changed.connect(lambda x: self._command_label.setText(x))

        self._model.property_changed += self._model_property_changed

    def set_is_capture_active(self, is_active: bool):
        self._tare_button.setEnabled(is_active)

    def set_selected_animal(self, animal: typing.Optional[AnimalSubject]):
        if animal is not None:
            self._x_pos.setValue(animal.pellet_x)
            self._y_pos.setValue(animal.pellet_y)
            self._z_pos.setValue(animal.pellet_z)
            self._position.setValue(animal.baseline_magnet_intensity)

    def _update_position(self):
        self._model.update_head_magnet_intensity(self._position.value())

    def _update_title(self, value: str):
        if value:
            if value.find("emulator") != -1:
                self._card_widget.header.setTitle(f"Hardware Control: Alogus Emulation")
            else:
                self._card_widget.header.setTitle(f"Hardware Control: {EnvironmentProvider.hardware_version()}")
        else:
            self._card_widget.header.setTitle("Hardware Control")

    def _model_property_changed(self, property_name: str, value, _):
        if property_name == HardwareModel.TUNNEL_VERSION_PROPERTY:
            self._update_title(value)
            if value:
                self._tunnel_version.setText(value.replace("emulator", "").strip())
            else:
                self._tunnel_version.setText("(unknown version)")
        elif property_name == HardwareModel.PELLET_VERSION_PROPERTY:
            self._update_title(value)
            if value:
                self._pellet_version.setText(value.replace("emulator", "").strip())
                self.setEnabled(True)
            else:
                self._pellet_version.setText("(unknown version)")
                self.setEnabled(False)
                self._command_label.setText("None")
        elif property_name == HardwareModel.PENDING_COMMAND_PROPERTY:
            if value:
                self.command_changed.emit(value.name)
                self.setEnabled(False)
            else:
                self.command_changed.emit("None")
                self.setEnabled(True)
