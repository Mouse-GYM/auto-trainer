import logging

from PySide6.QtWidgets import QLabel, QWidget, QHBoxLayout, QVBoxLayout, QPlainTextEdit

from autotrainer.pyside import CardWidget, TextBoxHandler
from tools.acquisition.model.app_model import AppModel


class DiagnosticsContent(QWidget):
    def __init__(self, model: AppModel):
        super().__init__()

        self._model = model

        self._card_widget = CardWidget()

        log_output = QPlainTextEdit()
        log_output.setReadOnly(True)
        log_output.setStyleSheet("border: 0px solid; border-color: #b9b9b9;")
        handler = TextBoxHandler(log_output)
        handler.setFormatter(logging.Formatter(fmt="%(asctime)s: %(levelname)s: %(name)s: %(message)s"))
        logging.getLogger().addHandler(handler)

        self._card_widget.setContentWidget(log_output)

        # Header
        self._header = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("Diagnostics")
        title.setStyleSheet("font-weight: bold")
        layout.addWidget(title)

        layout.addStretch(1)

        self._header.setLayout(layout)

        self._card_widget.header.setContent(self._header)

        # Final layout
        layout = QVBoxLayout()
        layout.addWidget(self._card_widget)
        self.setLayout(layout)
