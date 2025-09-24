from PySide6.QtWidgets import QWidget, QHBoxLayout, QFormLayout

from autotrainer.core import MessageHandler
from autotrainer.pyside import CardWidget, StatusIcon
from tools.pellet_delivery.model.app_model import AppModel


def _create_door_panel():
    layout = QFormLayout()
    layout.setHorizontalSpacing(8)

    front_door = StatusIcon.doorIcon()
    layout.addRow("Front Door:", front_door)

    drawer_door = StatusIcon.doorIcon()
    layout.addRow("Drawer Door:", drawer_door)

    ext_button = StatusIcon.doorIcon()
    layout.addRow("Ext Button:", ext_button)

    layout.setContentsMargins(8, 8, 8, 8)

    panel = CardWidget(title="Doors", content_layout=layout)

    return front_door, drawer_door, ext_button, panel


def _create_stimulus_panel():
    layout = QFormLayout()
    layout.setHorizontalSpacing(8)

    inputs = []
    for idx in range(4):
        box = StatusIcon()
        inputs.append(box)
        layout.addRow("Stimulus #" + str(idx + 1) + ':', box)

    layout.setContentsMargins(8, 8, 8, 8)

    panel = CardWidget(title="Stimulus", content_layout=layout)

    return inputs, panel


class PelletState(QWidget):
    def __init__(self, app_model: AppModel):
        super().__init__()

        self._app_model = app_model
        app_model.property_changed += self._model_property_changed

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        self._front_door, self._drawer_door, self._ext_button, panel = _create_door_panel()
        layout.addWidget(panel)

        self._stimulus, panel = _create_stimulus_panel()
        layout.addWidget(panel)

        self.setLayout(layout)

    def _model_property_changed(self, name: str, value, _old_value):
        app_model = self._app_model
        if name == "is_connected":
            if value:
                reset_prop = self._model_property_changed
                reset_prop(MessageHandler.FRONT_DOOR_PROPERTY, app_model.front_door, None)
                reset_prop(MessageHandler.DRAWER_DOOR_PROPERTY, app_model.panel_door, None)
                reset_prop(MessageHandler.EXT_BUTTON_PROPERTY, app_model.ext_button, None)
                reset_prop(MessageHandler.STIMULI_PROPERTY, app_model.stimuli, None)
            else:
                self._front_door.setStatus(False)
                self._drawer_door.setStatus(False)
                self._ext_button.setStatus(False)
                for box in self._stimulus:
                    box.setStatus(False)
        elif name == MessageHandler.FRONT_DOOR_PROPERTY:
            self._front_door.setStatus(bool(value))
        elif name == MessageHandler.DRAWER_DOOR_PROPERTY:
            self._drawer_door.setStatus(bool(value))
        elif name == MessageHandler.EXT_BUTTON_PROPERTY:
            self._ext_button.setStatus(bool(value))
        elif name == MessageHandler.STIMULI_PROPERTY:
            for v, box in zip(value, self._stimulus):
                box.setStatus(bool(v))
