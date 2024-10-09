from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QWidget, QVBoxLayout

from autotrainer.pyside import CardWidget
from tools.acquisition.view.content_widget import ContentWidget


class MetadataContent(ContentWidget):
    def __init__(self, model):
        super().__init__()

        self._model = model

        self._card_widget = CardWidget()

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

        self._content = QWidget()
        self._content.setLayout(layout)

        self._card_widget.setContentWidget(self._content)

        # Header
        self._header = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("Metadata")
        title.setStyleSheet("font-weight: bold")
        layout.addWidget(title)

        self._header.setLayout(layout)

        self._card_widget.header.setContent(self._header)

        # Final layout
        layout = QVBoxLayout()
        layout.addWidget(self._card_widget)
        self.setLayout(layout)

        self._model.property_changed += self._model_property_changed

        self.set_is_editable(False)

    def name_changed(self, value: str):
        self._model.animal_name = value

    def notes_changed(self, value: str):
        self._model.notes = value

    def _model_property_changed(self, name, value, _):
        if name == "animal_name":
            self._name.setText(value)
        if name == "notes":
            self._notes.setText(value)
