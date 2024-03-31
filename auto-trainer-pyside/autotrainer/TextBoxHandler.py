from logging import Handler

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QPlainTextEdit


class QSignaler(QObject):
    log_message = Signal(str)


class TextBoxHandler(Handler):
    def __init__(self, text_edit: QPlainTextEdit):
        Handler.__init__(self)

        self.emitter = QSignaler()

        self.text_edit = text_edit

        self.emitter.log_message.connect(lambda t: self.text_edit.appendPlainText(t))

    def emit(self, record):
        self.emitter.log_message.emit(self.format(record))
