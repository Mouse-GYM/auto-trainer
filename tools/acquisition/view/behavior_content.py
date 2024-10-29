from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton, QCheckBox, QFileDialog, QWidget, QVBoxLayout, \
    QHBoxLayout, QStackedLayout, QGridLayout

from autotrainer.pyside import CardWidget, QSwitch
from tools.acquisition.model.analysis_model import AnalysisModel
from tools.acquisition.model.behavior_model import BehaviorModel
from tools.acquisition.view.content_widget import ContentWidget


class BehaviorContent(ContentWidget):
    def __init__(self, behavior_model: BehaviorModel, analysis_model: AnalysisModel):
        super().__init__()

        self._behavior_model = behavior_model
        self._analysis_model = analysis_model

        self._card_widget = CardWidget()

        content = QWidget()
        content_layout = QGridLayout()
        content_layout.setRowStretch(3, 1)
        content_layout.setColumnStretch(2, 1)

        content_layout.addWidget(QLabel("Enable Inference:"))
        self._inference_enabled = QSwitch()
        self._inference_enabled.stateChanged.connect(self._is_enabled_state_changed)
        content_layout.addWidget(self._inference_enabled, 0, 1)

        content_layout.addWidget(QLabel("Enable Pellet Delivery:"), 1, 0)
        self._pellet_delivery_toggle = QSwitch()
        self._pellet_delivery_toggle.stateChanged.connect(self._pellet_delivery_state_changed)
        content_layout.addWidget(self._pellet_delivery_toggle, 1, 1)

        content_layout.addWidget(QLabel("Enable Pellet Cover:"), 2, 0)
        self._pellet_cover_toggle = QSwitch()
        self._pellet_cover_toggle.stateChanged.connect(self._pellet_cover_toggle_state_changed)
        content_layout.addWidget(self._pellet_cover_toggle, 2, 1)

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

        self._analysis_model_property_changed("model_location", self._analysis_model.model_location, None)
        self._analysis_model.property_changed += self._analysis_model_property_changed

        self._pellet_delivery_toggle.setChecked(self._behavior_model.algorithm.pellet_delivery_enabled)
        self._pellet_cover_toggle.setChecked(self._behavior_model.algorithm.pellet_cover_enabled)
        self._behavior_model.algorithm.property_changed += self._behavior_model_property_changed

        self.set_is_editable(False)

    def set_is_editable(self, is_editable: bool):
        self._stack_layout.setCurrentIndex(1 if is_editable else 0)

    def set_is_capture_active(self, is_active: bool):
        self._inference_enabled.setEnabled(not is_active)
        self._location.setEnabled(not is_active)
        self._browse_button.setEnabled(not is_active)

    def _is_enabled_state_changed(self, x: int):
        self._analysis_model.is_enabled = x != 0
        self._pellet_delivery_toggle.setEnabled(self._analysis_model.is_enabled)
        self._pellet_cover_toggle.setEnabled(
            self._analysis_model.is_enabled and self._behavior_model.algorithm.pellet_delivery_enabled)

    def _pellet_delivery_state_changed(self, x: int):
        self._behavior_model.algorithm.pellet_delivery_enabled = x != 0
        self._pellet_cover_toggle.setEnabled(self._behavior_model.algorithm.pellet_delivery_enabled)

    def _pellet_cover_toggle_state_changed(self, x: int):
        self._behavior_model.algorithm.pellet_cover_enabled = x != 0

    def _location_changed(self):
        self._analysis_model.model_location = self._location.text()

    def _browse_for_location(self):
        dirname = QFileDialog.getExistingDirectory(self, "Select Directory", self._location.text())

        if len(dirname) > 0:
            self._location.setText(dirname)
            self._analysis_model.model_location = dirname

    def _behavior_model_property_changed(self, name, value, _):
        if name == "pellet_delivery_enabled":
            self._pellet_delivery_toggle.setChecked(value)
        elif name == "pellet_cover_enabled":
            self._pellet_cover_toggle.setChecked(value)

    def _analysis_model_property_changed(self, name, value, _):
        if name == "is_enabled":
            self._inference_enabled.setChecked(value)
        elif name == "model_location":
            if value is not None and len(value) > 0:
                self._location.setText(value)
                self._location_label.setText(value)
            else:
                self._location.setText("Inference model not specified")
                self._location_label.setText("Inference model not specified")
