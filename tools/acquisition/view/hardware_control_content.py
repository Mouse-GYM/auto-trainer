from typing import Optional
from functools import partial

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (QLabel, QSpinBox, QWidget, QPushButton, QVBoxLayout, QHBoxLayout, QGridLayout,
                               QFormLayout, QStackedLayout, QSizePolicy, QComboBox, QDoubleSpinBox)

from autotrainer.core import AnimalSubject, Offset3DTuple
from autotrainer.core.logging import get_verbose_logger

from autotrainer.model import EnvironmentProvider, HardwareVersion

from autotrainer.pyside import CardWidget
from autotrainer.pyside.StackedContent import StackedLayout
from autotrainer.pyside.content_widget import ContentWidget
from tools.acquisition.model.app_model import AppModel

from tools.acquisition.model.hardware_model import HardwareModel


logger = get_verbose_logger(__name__)


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

    def __init__(self, app_model: AppModel):
        super().__init__()

        self._app_model = app_model
        self._hardware_model = app_model.hardware

        # Header
        layout = QHBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        layout.setSpacing(8)

        layout.addWidget(QLabel("Tunnel:"))
        self._tunnel_version = QLabel("(unknown version)")
        layout.addWidget(self._tunnel_version)

        layout.addWidget(QLabel("Pellet:"))
        self._pellet_version = QLabel("(unknown version)")
        layout.addWidget(self._pellet_version)

        self._card_widget = CardWidget(title="Hardware Control", header_right_layout=layout)
        # self._card_widget.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Preferred)

        if EnvironmentProvider.hardware_version() == HardwareVersion.ANSHUTZ:
            self._travel_limits = _anshutz_travel_limits
        else:
            self._travel_limits = _alogus_travel_limits

        layout = QGridLayout()
        layout.setContentsMargins(8, 4, 8, 6)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        label = QLabel("<b>Tunnel</b>")
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label, 0, 0)
        vbox = QVBoxLayout()
        label = QLabel("<b>Pellet Release Location (mm)</b>")
        label.setAlignment(Qt.AlignCenter)
        vbox.addWidget(label)
        label = self._is_motor_cs_label = QLabel("<b>@ MotorCoordSystem</b>")
        if app_model.behavior.algorithm.diamond_triangle_config is not None:
            label.hide()
        label.setAlignment(Qt.AlignCenter)
        vbox.addWidget(label)
        layout.addLayout(vbox, 0, 2)

        label = QLabel("<b>Compound Move</b>")
        label.setAlignment(Qt.AlignCenter)
        label.setContentsMargins(0, 0, 0, 4)  # ensure small margin below
        layout.addWidget(label, 0, 4)

        form_layout = QFormLayout()
        form_layout.setContentsMargins(0, 4, 0, 0)
        form_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        form_layout.setHorizontalSpacing(8)
        form_layout.setVerticalSpacing(4)

        spinbox = self._head_magnet_position_spinbox = QSpinBox()
        spinbox.setValue(0)
        spinbox.setMaximum(100)
        spinbox.setWrapping(False)
        button = self._head_magnet_move_button = QPushButton("Move")
        def clicked():
            self._hardware_model.update_head_magnet_intensity(self._head_magnet_position_spinbox.value())
        button.clicked.connect(clicked)

        right_layout = QHBoxLayout()
        right_layout.setSpacing(4)
        right_layout.addWidget(self._head_magnet_position_spinbox)
        right_layout.addWidget(self._head_magnet_move_button)
        form_layout.addRow("Head magnet intensity (%):", right_layout)

        self._tare_button = QPushButton("Tare")
        self._tare_button.setEnabled(False)
        self._tare_button.clicked.connect(self._hardware_model.tare_load_cell)
        form_layout.addRow(QLabel("Load cell:"), self._tare_button)

        layout.addLayout(form_layout, 1, 0)

        algo = app_model.behavior.algorithm

        def set_xyz(coord: str):
            value = getattr(self, f"_{coord}_pos").value()
            coord_idx = "xyz".index(coord)
            assert coord_idx in (0, 1, 2)
            t = [self._x_pos.value(), self._y_pos.value(), self._z_pos.value()]
            t[coord_idx] = value
            xyz = Offset3DTuple(*t)
            cfg = algo.diamond_triangle_config
            if cfg is not None:
                xyz = cfg.diamond_to_motor(xyz)
            value = xyz[coord_idx]
            meth = getattr(self._hardware_model, f"set_{coord}")
            meth(value)

        sub_layout = QGridLayout()
        sub_layout.setContentsMargins(0, 0, 0, 0)
        sub_layout.setHorizontalSpacing(4)
        sub_layout.setVerticalSpacing(4)
        sub_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        row = col = 0

        def add_coord(coord: str):
            nonlocal row
            pos = QDoubleSpinBox()
            pos.setValue(0)
            pos.setContentsMargins(0, 0, 0, 0)
            pos.setMinimumWidth(60)
            pos.setDecimals(1)
            pos.setSingleStep(0.5)
            pos.setAlignment(Qt.AlignmentFlag.AlignRight)
            range_label = QLabel()
            set_button = QPushButton("Set")
            set_button.clicked.connect(partial(set_xyz, coord))
            sub_layout.addWidget(QLabel(f"{coord.upper()} :"), row, col)
            sub_layout.addWidget(pos, row, col + 1)
            sub_layout.addWidget(range_label, row, col + 2)
            sub_layout.addWidget(set_button, row, col + 3)
            row += 1
            return pos, set_button, range_label

        self._x_pos, self._x_set_button, self._x_range_label = add_coord('x')
        self._y_pos, self._y_set_button, self._y_range_label = add_coord('y')
        self._z_pos, self._z_set_button, self._z_range_label = add_coord('z')

        layout.addLayout(sub_layout, 1, 2, alignment=Qt.AlignmentFlag.AlignTop)

        self._set_pos_limits()

        #

        button_layout = QVBoxLayout()
        button_layout.setSpacing(4)
        self._home_button = QPushButton("Home")
        self._home_button.clicked.connect(lambda: self._hardware_model.send_home())
        button_layout.addWidget(self._home_button)
        self._load_button = QPushButton("Load")
        self._load_button.clicked.connect(lambda: self._hardware_model.load_pellet())
        button_layout.addWidget(self._load_button)
        self._send_button = QPushButton("Send")
        self._send_button.clicked.connect(lambda: self._hardware_model.send_pellet())
        button_layout.addWidget(self._send_button)
        self._release_button = QPushButton("Release")
        self._release_button.clicked.connect(lambda: self._hardware_model.release_pellet())
        button_layout.addWidget(self._release_button)
        self._cover_button = QPushButton("Cover")
        self._cover_button.clicked.connect(lambda: self._hardware_model.cover_pellet())
        button_layout.addWidget(self._cover_button)
        layout.addLayout(button_layout, 1, 4)

        # central layout/widget
        widget = QWidget()
        widget.setLayout(layout)
        # widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Pre)
        self._card_widget.setContentWidget(widget)

        # Footer
        self._basic_footer = QWidget()
        layout = QHBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Command in progress:"))
        self._command_label = QLabel("None")
        layout.addWidget(self._command_label)
        self._basic_footer.setLayout(layout)
        self._stack_layout = StackedLayout()
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
        # self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        self.setEnabled(False)

        self.command_changed.connect(lambda x: self._command_label.setText(x))

        self._hardware_model.property_changed += self._model_property_changed

    def _set_pos_limits(self):
        limits = self._travel_limits
        if limits is not None:
            algo = self._app_model.behavior.algorithm
            min_xyz = Offset3DTuple(*(limits[c][0] for c in 'xyz'))
            max_xyz = Offset3DTuple(*(limits[c][1] for c in 'xyz'))
            diamond_triangle_cfg = algo.diamond_triangle_config
            if diamond_triangle_cfg is not None:
                min_xyz = diamond_triangle_cfg.motor_to_diamond(min_xyz)
                max_xyz = diamond_triangle_cfg.motor_to_diamond(max_xyz)
            for idx, pos in enumerate((self._x_pos, self._y_pos, self._z_pos)):
                c = "xyz"[idx]
                v1, v2 = min_xyz[idx], max_xyz[idx]
                r = min(v1, v2), max(v1, v2)
                pos.setRange(*r)
                getattr(self, f"_{c}_range_label").setText(f"[ {r[0]:>5.1f} : {r[1]:<5.1f}]")

    def set_is_capture_active(self, is_active: bool):
        self._tare_button.setEnabled(is_active)

    def set_selected_animal(self, animal: Optional[AnimalSubject]):
        if animal is not None:
            self._set_pos_limits()
            xyz = Offset3DTuple(animal.pellet_x, animal.pellet_y, animal.pellet_z)
            algo = self._app_model.behavior.algorithm
            cfg = algo.diamond_triangle_config
            if animal.is_pellet_dcs or cfg is not None:
                logger.debug("Displaying animal data with Diamond coordinate system")
                self._is_motor_cs_label.hide()
                if not animal.is_pellet_dcs:
                    xyz = cfg.motor_to_diamond(xyz)
            else:
                assert not animal.is_pellet_dcs and cfg is None
                logger.notice("Displaying animal data with Motor coordinate system")
                self._is_motor_cs_label.show()

            for widget, value in (
                (self._x_pos, xyz.x),
                (self._y_pos, xyz.y),
                (self._z_pos, xyz.z),
                (self._head_magnet_position_spinbox, animal.baseline_magnet_intensity)
            ):
                assert isinstance(widget, (QDoubleSpinBox, QSpinBox))
                widget.blockSignals(True)
                widget.setValue(value)
                widget.blockSignals(False)
            self.update()

    def _update_head_magnet_position(self):
        self._hardware_model.update_head_magnet_intensity(self._head_magnet_position_spinbox.value())

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
