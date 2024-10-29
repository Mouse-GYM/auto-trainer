from PySide6.QtWidgets import QLabel, QLineEdit, QWidget, QHBoxLayout, QVBoxLayout, QStackedLayout

from autotrainer.pyside import CardWidget
from tools.acquisition.model.app_model import AppModel
from tools.acquisition.view.content_widget import ContentWidget


class OutputContent(ContentWidget):
    def __init__(self, model: AppModel):
        super().__init__()

        self._model = model

        self._card_widget = CardWidget()

        content_layout = QVBoxLayout()

        # Metadata
        layout = QHBoxLayout()

        layout.addWidget(QLabel("Name:"))
        self._name = QLineEdit()
        self._name.setText(self._model.animal_name)
        self._name.textChanged.connect(self.name_changed)
        layout.addWidget(self._name)

        layout.addWidget(QLabel("Notes:"))
        self._notes = QLineEdit()
        self._notes.setText(self._model.notes)
        self._notes.textChanged.connect(self.notes_changed)
        layout.addWidget(self._notes)

        widget = QWidget()
        widget.setLayout(layout)

        content_layout.addWidget(widget)

        # Output location
        layout = QHBoxLayout()

        layout.addWidget(QLabel("Top-Level Location:"))

        self._location = QLineEdit()
        self._location.setText(self._model.output_location)
        self._location.textChanged.connect(self.location_changed)
        layout.addWidget(self._location)

        self._content = QWidget()
        self._content.setLayout(layout)

        self._no_content = QWidget()

        self._stacked_layout = QStackedLayout()
        self._stacked_layout.addWidget(self._no_content)
        self._stacked_layout.addWidget(self._content)

        widget = QWidget()
        widget.setLayout(self._stacked_layout)

        content_layout.addWidget(widget)

        # All
        widget = QWidget()
        widget.setLayout(content_layout)
        self._card_widget.setContentWidget(widget)

        # Header
        self._header = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("Output")
        title.setStyleSheet("font-weight: bold")
        layout.addWidget(title)

        layout.addStretch(1)

        self._output_location_header = QLabel("")

        layout.addWidget(self._output_location_header)

        self._header.setLayout(layout)

        self._card_widget.header.setContent(self._header)

        # Final layout
        layout = QVBoxLayout()
        layout.addWidget(self._card_widget)
        self.setLayout(layout)

        self._model.property_changed += self._model_property_changed

        self.set_is_editable(False)

    def set_is_editable(self, is_editable: bool):
        self._stacked_layout.setCurrentIndex(1 if is_editable else 0)

    def set_is_capture_active(self, is_active: bool):
        self._location.setEnabled(not is_active)

    def location_changed(self, value: str):
        self._model.output_location = value

    def name_changed(self, value: str):
        self._model.animal_name = value

    def notes_changed(self, value: str):
        self._model.notes = value

    def _model_property_changed(self, name, value, _):
        if name == "output_location":
            self._location.setText(value)
            self._output_location_header.setText(value)
        if name == "animal_name":
            self._name.setText(value)
        if name == "notes":
            self._notes.setText(value)
