import contextlib

from PySide6.QtCore import QObject


@contextlib.contextmanager
def signals_blocked(obj: QObject):
    obj.blockSignals(True)
    try:
        yield
    finally:
        obj.blockSignals(False)
