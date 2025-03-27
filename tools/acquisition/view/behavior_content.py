from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton, QCheckBox, QFileDialog, QWidget, QVBoxLayout, \
    QHBoxLayout, QStackedLayout, QGridLayout, QSpinBox

from autotrainer.pyside import CardWidget, QSwitch
from tools.acquisition.model.head_fix_model import HeadFixModel
from tools.acquisition.model.inference_model import InferenceModel
from tools.acquisition.model.behavior_model import BehaviorModel
from tools.acquisition.view.content_widget import ContentWidget


class BehaviorContent(ContentWidget):
    status_changed = Signal(str)

    def __init__(self, behavior_model: BehaviorModel, inference_model: InferenceModel, head_fix_model: HeadFixModel):
        super().__init__()

        self._behavior_model = behavior_model
        self._inference_model = inference_model
        self._head_fix_model = head_fix_model

        self._card_widget = CardWidget()

        content = QWidget()
        content_layout = QGridLayout()
        content_layout.setRowStretch(3, 1)
        content_layout.setColumnStretch(6, 1)

        content_layout.addWidget(QLabel("Live Analysis:"))
        self._inference_enabled = QSwitch()
        self._inference_enabled.stateChanged.connect(self._is_enabled_state_changed)
        content_layout.addWidget(self._inference_enabled, 0, 1)

        content_layout.addWidget(QLabel("Deliver Pellets:"), 1, 0)
        self._pellet_delivery_toggle = QSwitch()
        self._pellet_delivery_toggle.stateChanged.connect(self._pellet_delivery_state_changed)
        content_layout.addWidget(self._pellet_delivery_toggle, 1, 1)

        content_layout.addWidget(QLabel("Cover Pellets:"), 2, 0)
        self._pellet_cover_toggle = QSwitch()
        self._pellet_cover_toggle.stateChanged.connect(self._pellet_cover_toggle_state_changed)
        content_layout.addWidget(self._pellet_cover_toggle, 2, 1)

        content_layout.addWidget(QLabel("Intersession Analysis:"), 0, 2)
        self._intersession_toggle = QSwitch()
        self._intersession_toggle.stateChanged.connect(self._intersession_toggle_state_changed)
        content_layout.addWidget(self._intersession_toggle, 0, 3)

        content_layout.addWidget(QLabel("Auto-Clamp:"), 0, 4)
        self._head_fixation_toggle = QSwitch()
        self._head_fixation_toggle.stateChanged.connect(self._head_fixation_toggle_state_changed)
        content_layout.addWidget(self._head_fixation_toggle, 0, 5)

        content_layout.addWidget(QLabel("Auto-Clamp Threshold:"), 1, 4)
        self._auto_clamp_threshold = QSpinBox()
        self._auto_clamp_threshold.setValue(self._head_fix_model.head_fix_reader.force_detector.threshold)
        self._auto_clamp_threshold.setMinimum(0)
        self._auto_clamp_threshold.setMaximum(1023)
        self._auto_clamp_threshold.setWrapping(False)
        self._auto_clamp_threshold.valueChanged.connect(self._update_auto_clamp_intensity)
        content_layout.addWidget(self._auto_clamp_threshold, 1, 5)

        content.setLayout(content_layout)
        self._card_widget.setContentWidget(content)

        # Header
        self._header = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("Behavior")
        title.setStyleSheet("font-weight: bold")
        layout.addWidget(title)

        layout.addStretch(1)

        self._inference_status = QLabel()
        layout.addWidget(self._inference_status)

        self._header.setLayout(layout)

        self._card_widget.header.setContent(self._header)

        # Footer
        self._editable_footer = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(QLabel("Inference Model:"))

        self._location = QLineEdit()
        self._location.editingFinished.connect(self._location_changed)
        layout.addWidget(self._location, 1)

        self._browse_button = QPushButton("Select...")
        self._browse_button.clicked.connect(self._browse_for_location)
        layout.addWidget(self._browse_button)

        self._editable_footer.setLayout(layout)

        self._basic_footer = QWidget()

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Inference model:"))
        self._location_label = QLabel()
        layout.addWidget(self._location_label)
        layout.addStretch(1)

        self._basic_footer.setLayout(layout)

        self._stack_layout = QStackedLayout()
        self._stack_layout.addWidget(self._basic_footer)
        self._stack_layout.addWidget(self._editable_footer)

        widget = QWidget()
        widget.setLayout(self._stack_layout)

        self._card_widget.footer.setContent(widget)

        # Final layout
        layout = QVBoxLayout()
        layout.addWidget(self._card_widget)
        self.setLayout(layout)

        self._inference_model_property_changed("model_location", self._inference_model.model_location, None)
        self._inference_model.property_changed += self._inference_model_property_changed

        self._inference_status.setText(f"Inference: {self._inference_model.status}")

        self._pellet_delivery_toggle.setChecked(self._behavior_model.algorithm.pellet_delivery_enabled)
        self._pellet_cover_toggle.setChecked(self._behavior_model.algorithm.pellet_cover_enabled)
        self._intersession_toggle.setChecked(self._behavior_model.is_intersession_enabled)
        self._behavior_model.algorithm.property_changed += self._algorithm_property_changed
        self._head_fix_model.head_fix_reader.force_detector.property_changed += self._force_detector_property_changed

        self._behavior_model.property_changed += self._behavior_model_property_changed

        self.status_changed.connect(lambda x: self._inference_status.setText(x))

        self.set_is_editable(False)

    def set_is_editable(self, is_editable: bool):
        self._stack_layout.setCurrentIndex(1 if is_editable else 0)

    def set_is_capture_active(self, is_active: bool):
        self._inference_enabled.setEnabled(not is_active)
        self._location.setEnabled(not is_active)
        self._browse_button.setEnabled(not is_active)

    def _is_enabled_state_changed(self, x: int):
        self._inference_model.is_enabled = x != 0
        self._pellet_delivery_toggle.setEnabled(self._inference_model.is_enabled)
        self._pellet_cover_toggle.setEnabled(
            self._inference_model.is_enabled and self._behavior_model.algorithm.pellet_delivery_enabled)

    def _pellet_delivery_state_changed(self, x: int):
        self._behavior_model.algorithm.pellet_delivery_enabled = x != 0
        self._pellet_cover_toggle.setEnabled(self._behavior_model.algorithm.pellet_delivery_enabled)

    def _pellet_cover_toggle_state_changed(self, x: int):
        self._behavior_model.algorithm.pellet_cover_enabled = x != 0

    def _intersession_toggle_state_changed(self, x: int):
        self._behavior_model.is_intersession_enabled = x != 0

    def _head_fixation_toggle_state_changed(self, x: int):
        self._behavior_model.algorithm.head_fixation_enabled = x != 0

    def _location_changed(self):
        self._inference_model.model_location = self._location.text()

    def _update_auto_clamp_intensity(self, value):
        self._head_fix_model.head_fix_reader.force_detector.threshold = value

    def _browse_for_location(self):
        dirname = QFileDialog.getExistingDirectory(self, "Select Directory", self._location.text())

        if len(dirname) > 0:
            self._location.setText(dirname)
            self._inference_model.model_location = dirname

    def _algorithm_property_changed(self, name, value, _):
        if name == "pellet_delivery_enabled":
            self._pellet_delivery_toggle.setChecked(value)
        elif name == "pellet_cover_enabled":
            self._pellet_cover_toggle.setChecked(value)

    def _behavior_model_property_changed(self, name, value, _):
        if name == "is_intersession_enabled":
            self._intersession_toggle.setChecked(value)

    def _force_detector_property_changed(self, name, value, _):
        if name == "threshold":
            self._auto_clamp_threshold.setValue(value)

    def _inference_model_property_changed(self, name, value, _):
        if name == "is_enabled":
            self._inference_enabled.setChecked(value)
        elif name == "status":
            self.status_changed.emit(f"Inference: {value}")
        elif name == "model_location":
            if value is not None and len(value) > 0:
                self._location.setText(value)
                self._location_label.setText(value)
            else:
                self._location.setText("Inference model not specified")
                self._location_label.setText("Inference model not specified")
