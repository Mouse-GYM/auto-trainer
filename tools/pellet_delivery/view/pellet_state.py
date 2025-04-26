from PySide6.QtWidgets import QWidget, QHBoxLayout, QFormLayout, QLabel

from autotrainer.core import MessageHandler
from tools.pellet_delivery.model.app_model import AppModel
from tools.view.basic_panel import create_panel

import qtawesome as qta


class Led(QLabel):
    LED_SIZE = 18

    def __init__(self, use_red: bool = False, parent=None):
        super(Led, self).__init__(parent)

        self._use_red = use_red
        self.setFixedSize(Led.LED_SIZE, Led.LED_SIZE)
        self.green_led = qta.icon('fa5s.life-ring', color='green')
        self.red_led = qta.icon('fa5s.life-ring', color='red')
        self.gray_led = qta.icon('fa5s.life-ring', color='gray')

        self.off()

    def on(self):
        self.setPixmap(self.green_led.pixmap(Led.LED_SIZE, Led.LED_SIZE))

    def off(self):
        led = self.red_led if self._use_red else self.gray_led
        self.setPixmap(led.pixmap(Led.LED_SIZE, Led.LED_SIZE))

    def set_light(self, setting: bool):
        self.on() if setting else self.off()


def _create_door_panel():
    layout = QFormLayout()
    front_door = Led()
    layout.addRow("Front Door:", front_door)

    drawer_door = Led()
    layout.addRow("Drawer Door:", drawer_door)

    return front_door, drawer_door, create_panel("Doors", layout)


def _create_stimulus_panel():
    layout = QFormLayout()
    inputs = []
    for i in range(4):
        box = Led()
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
                self._front_door.set_light(False)
                self._drawer_door.set_light(False)
        elif name == MessageHandler.FRONT_DOOR_PROPERTY:
            self._front_door.set_light(bool(value))
        elif name == MessageHandler.DRAWER_DOOR_PROPERTY:
            self._drawer_door.set_light(bool(value))
        elif name == MessageHandler.STIMULI_PROPERTY:
            for v, box in zip(value, self._stimulus):
                box.set_light(bool(v))
