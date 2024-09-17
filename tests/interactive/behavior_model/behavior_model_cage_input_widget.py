from PySide6.QtWidgets import QWidget, QLabel, QPushButton, QVBoxLayout

from tools.acquisition.behavior.cage_model import CageModel


class BehaviorModelCageInputWidget(QWidget):
    def __init__(self, cage_model: CageModel):
        super().__init__()

        self._cage_model = cage_model

        layout = QVBoxLayout()

        self.mouse_present = QLabel(f"Mouse present: {self._cage_model.mouse_present()}")
        layout.addWidget(self.mouse_present)

        self.detect_mouse_button = QPushButton("Mouse Detected")
        layout.addWidget(self.detect_mouse_button)

        self.setLayout(layout)

        def set_is_mouse_present():
            self._cage_model.detection_complete()

        self.detect_mouse_button.pressed.connect(set_is_mouse_present)

        self._cage_model.properties.property_changed += self.cage_model_property_changed

    def cage_model_property_changed(self, name: str, value, old_value):
        self.mouse_present.setText(f"Mouse present: {value}")
