import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QPlainTextEdit


class QSignaler(QObject):
    log_message = Signal(str)


class TextBoxHandler(logging.Handler):
    def __init__(self, text_edit: QPlainTextEdit):
        super().__init__()
        self.emitter = QSignaler()
        self.text_edit = text_edit
        self.emitter.log_message.connect(self.text_edit.appendPlainText)
        self._is_visible = False

    def setVisible(self, visible: bool):
        self._is_visible = visible

    def emit(self, record):
        if self._is_visible:
            try:
                data = self.format(record)
            except Exception:
                self.handleError(record)
            else:
                self.emitter.log_message.emit(data)
