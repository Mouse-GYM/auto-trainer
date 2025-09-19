
from PySide6 import QtCore
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QLabel, QFileDialog, QWidget, QVBoxLayout,
                               QHBoxLayout, QStackedLayout, QGridLayout, QSpinBox, QPushButton)

from autotrainer.behavior.behavior_algorithm import BehaviorAlgoProps
from autotrainer.pyside import CardWidget, QSwitch
from tools.acquisition.model.inference_model import InferenceModel
from tools.acquisition.model.behavior_model import BehaviorModel
from tools.acquisition.view.content_widget import ContentWidget


class BehaviorContent(ContentWidget):
    status_changed = Signal(str, name="status_changed")

    def __init__(self, behavior_model: BehaviorModel, inference_model: InferenceModel):
        super().__init__()

        self._behavior_model = behavior_model
        self._inference_model = inference_model
        self._analysis = behavior_model.analysis

        self._inference_status = QLabel("")
        self._card_widget = CardWidget(title="Behavior", header_right_layout=self._inference_status)

        content = QWidget(None)
        content_layout = QGridLayout(None)
        content_layout.setRowStretch(3, 1)
        content_layout.setColumnStretch(4, 1)

        content_layout.addWidget(QLabel("Intersession Analysis:"), 0, 0)
        toggle = self._intersession_toggle = QSwitch()
        toggle.stateChanged.connect(self._intersession_toggle_state_changed)
        toggle.setToolTip(
            "Enables reach detection and segmentation after each session where the mouse is seen.  This may modify "
            "pellet counts and adjust the pellet delivery position.")
        content_layout.addWidget(toggle, 0, 1)

        content_layout.addWidget(QLabel("Auto-Clamp:"), 1, 0)
        self._head_fixation_toggle = QSwitch()
        self._head_fixation_toggle.stateChanged.connect(self._head_fixation_toggle_state_changed)
        self._head_fixation_toggle.setToolTip(
            "Enables automatic magnet adjustment to 100% when the headbar detector is triggered.")
        content_layout.addWidget(self._head_fixation_toggle, 1, 1)

        baseline_layout = QHBoxLayout()
        baseline_layout.addWidget(QLabel("Head Magnet Baseline: "))
        self._baseline = QLabel(f"{self._behavior_model.algorithm.baseline_intensity}%")
        baseline_layout.addWidget(self._baseline)
        self._make_baseline_button = QPushButton("Make Current Position Baseline")
        self._make_baseline_button.clicked.connect(self._make_position_baseline)
        baseline_layout.addWidget(self._make_baseline_button)
        baseline_layout.addStretch(1)
        content_layout.addLayout(baseline_layout, 3, 0, 1, 6)

        content.setLayout(content_layout)
        self._card_widget.setContentWidget(content)

        # Footer
        self._basic_footer = QWidget(None)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Inference model:"))
        self._location_label = QLabel("")
        layout.addWidget(self._location_label)
        layout.addStretch(1)

        self._basic_footer.setLayout(layout)

        self._stack_layout = QStackedLayout()
        self._stack_layout.addWidget(self._basic_footer)

        widget = QWidget(None)
        widget.setLayout(self._stack_layout)

        self._card_widget.footer.setContent(widget)

        # Final layout
        layout = QVBoxLayout()
        layout.addWidget(self._card_widget)
        self.setLayout(layout)

        self._inference_model_property_changed("model_location", self._inference_model.model_location, None)
        self._inference_model.property_changed += self._inference_model_property_changed

        self._inference_status.setText(f"Inference: {self._inference_model.status}")

        self._intersession_toggle.setChecked(self._behavior_model.is_intersession_enabled)

        self._behavior_model.algorithm.property_changed += self._algorithm_property_changed
        # self._analysis.headbar_pressure_monitor.property_changed += self._force_detector_property_changed
        self._behavior_model.property_changed += self._behavior_model_property_changed

        self.status_changed.connect(lambda x: self._inference_status.setText(x))

        self.set_is_editable(False)

    def set_is_editable(self, is_editable: bool):
        self._stack_layout.setCurrentIndex(1 if is_editable else 0)

    def set_is_capture_active(self, is_active: bool):
        pass

    def _intersession_toggle_state_changed(self, x: int):
        self._behavior_model.is_intersession_enabled = x != 0

    def _head_fixation_toggle_state_changed(self, x: int):
        self._behavior_model.algorithm.head_fixation_enabled = x != 0

    def _make_position_baseline(self):
        self._behavior_model.use_current_head_magnet_position_as_baseline()

    def _algorithm_property_changed(self, name, value, _):
        if name == BehaviorAlgoProps.BASELINE_INTENSITY:
            self._baseline.setText(f"{value}%")

    def _behavior_model_property_changed(self, name, value, _):
        if name == "is_intersession_enabled":
            self._intersession_toggle.setChecked(value)

    def _inference_model_property_changed(self, name, value, _):
        if name == "is_enabled":
            self._intersession_toggle.setEnabled(value)
        elif name == "status":
            self.status_changed.emit(f"Inference: {value}")
        elif name == "model_location":
            if value is not None and len(value) > 0:
                self._location_label.setText(value)
            else:
                self._location_label.setText("Inference model not specified")
