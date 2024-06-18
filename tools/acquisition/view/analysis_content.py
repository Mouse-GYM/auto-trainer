from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton, QCheckBox, QFileDialog, QWidget, QVBoxLayout, \
    QHBoxLayout, QFormLayout, QStackedLayout

from autotrainer.pyside import CardWidget
from tools.acquisition.model.analysis_model import AnalysisModel
from tools.acquisition.view.ContentWidget import ContentWidget


class AnalysisContent(ContentWidget):
    def __init__(self, model: AnalysisModel):
        super().__init__()

        self._model = model

        self._card_widget = CardWidget()

        content = QWidget()
        layout = QFormLayout()

        content.setLayout(layout)
        self._card_widget.setContentWidget(content)

        # Header
        self._header = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("Analysis")
        title.setStyleSheet("font-weight: bold")
        layout.addWidget(title)

        layout.addStretch(1)

        self._is_enabled = QCheckBox("Enable")
        self._is_enabled.setChecked(self._model.is_enabled)
        self._is_enabled.stateChanged.connect(self._is_enabled_state_changed)
        layout.addWidget(self._is_enabled)

        self._enabled_label = QLabel("Enabled" if self._model.is_enabled else "Disabled")
        layout.addWidget(self._enabled_label)

        self._header.setLayout(layout)

        self._card_widget.header.setContent(self._header)

        # Footer
        self._editable_footer = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(QLabel("Model:"))

        self._location = QLineEdit(self._model.model_location)
        self._location.editingFinished.connect(self._location_changed)
        layout.addWidget(self._location, 1)

        self._browse_button = QPushButton("Select...")
        self._browse_button.clicked.connect(self._browse_for_location)
        layout.addWidget(self._browse_button)

        self._editable_footer.setLayout(layout)

        self._basic_footer = QWidget()

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self._location_label = QLabel(self._model.model_location)
        layout.addWidget(self._location_label)

        self._basic_footer.setLayout(layout)

        self._stack_layout = QStackedLayout()
        # self._stack_layout.setContentsMargins(0, 0, 0, 0)
        self._stack_layout.addWidget(self._basic_footer)
        self._stack_layout.addWidget(self._editable_footer)

        widget = QWidget()
        widget.setLayout(self._stack_layout)

        self._card_widget.footer.setContent(widget)

        # Final layout
        layout = QVBoxLayout()
        layout.addWidget(self._card_widget)
        self.setLayout(layout)

        self._model.events.property_changed += self._model_property_changed

        self.set_is_editable(False)

    def set_is_editable(self, is_editable: bool):
        self._is_enabled.setVisible(is_editable)
        self._enabled_label.setVisible(not is_editable)
        self._stack_layout.setCurrentIndex(1 if is_editable else 0)

    def set_is_capture_active(self, is_active: bool):
        self._is_enabled.setEnabled(not is_active)
        self._location.setEnabled(not is_active)
        self._browse_button.setEnabled(not is_active)

    def _is_enabled_state_changed(self, x: int):
        self._model.is_enabled = x != 0
        self._enabled_label.setText("Enabled" if self._model.is_enabled else "Disabled")

    def _location_changed(self):
        self._model.model_location = self._location.text()

    def _browse_for_location(self):
        dirname = QFileDialog.getExistingDirectory(self, "Select Directory", self._location.text())

        if len(dirname) > 0:
            self._location.setText(dirname)
            self._model.model_location = dirname

    def _model_property_changed(self, name, value, _):
        if name == "is_enabled":
            self._is_enabled.setChecked(value)
        elif name == "model_location":
            self._location.setText(value)
            self._location_label.setText(value)
