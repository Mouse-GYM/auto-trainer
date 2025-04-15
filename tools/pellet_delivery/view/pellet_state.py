from PySide6.QtWidgets import QWidget, QGridLayout, QHBoxLayout, \
    QCheckBox, QFormLayout

from tools.pellet_delivery.model.app_model import AppModel
from tools.view.basic_panel import create_panel


def _create_door_panel():
    layout = QFormLayout()
    front_door = QCheckBox()
    front_door.nextCheckState = lambda: None
    layout.addRow("Front Door:", front_door)

    drawer_door = QCheckBox()
    drawer_door.nextCheckState = lambda: None
    layout.addRow("Drawer Door:", drawer_door)

    return front_door, drawer_door, create_panel("Doors", layout)


def _create_stimulus_panel():
    layout = QFormLayout()
    inputs = []
    for i in range(4):
        box = QCheckBox()
        box.nextCheckState = lambda: None
        inputs.append(box)
        layout.addRow("Stimulus #" + str(i + 1) + ':', box)

    return inputs, create_panel("Stimulus", layout)


class PelletState(QWidget):
    def __init__(self, app_model: AppModel):
        super().__init__()

        self._app_model: AppModel = app_model

        self._app_model.property_changed += self._model_property_changed

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        self._front_door, self._drawer_door, panel = _create_door_panel()
        layout.addWidget(panel)

        self._stimulus, panel = _create_stimulus_panel()
        layout.addWidget(panel)

        self.setLayout(layout)

    def _model_property_changed(self, name: str, value, _old_value):
        if name == "is_connected":
            if not value:
                self._front_door.setChecked(False)
                self._drawer_door.setChecked(False)
        elif name == "front_door":
            self._front_door.setChecked(bool(value))
        elif name == "drawer_door":
            self._drawer_door.setChecked(bool(value))
        elif name == "stimuli":
            for v, box in zip(value, self._stimulus):
                box.setChecked(bool(v))
