from typing import Callable

from PySide6.QtWidgets import QWidget

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QGuiApplication


class InvokeMethod(QObject):
    def __init__(self, method: Callable):
        """
        Invokes a method on the main thread. Taking care of garbage collection "bugs".
        """
        super().__init__()

        main_thread = QGuiApplication.instance().thread()
        self.moveToThread(main_thread)
        self.setParent(QGuiApplication.instance())
        self.method = method
        self.called.connect(self.execute)
        self.called.emit()

    called = Signal()

    @Slot()
    def execute(self):
        self.method()
        # trigger garbage collector
        self.setParent(None)


class ContentWidget(QWidget):
    def __init__(self):
        super().__init__()

    def set_is_editable(self, is_editable: bool):
        pass

    def set_is_capture_active(self, is_active: bool):
        pass

    def on_activated(self):
        pass

    def on_close(self):
        pass
