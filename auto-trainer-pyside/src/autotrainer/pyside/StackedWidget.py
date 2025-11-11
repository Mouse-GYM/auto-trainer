from PySide6.QtWidgets import QStackedWidget


class StackedWidget(QStackedWidget):
    """QStackedWidget which set its size hint and minimum size to the currently selected child widget"""

    def __init__(self):
        super().__init__()

    def minimumSize(self):
        current = self.currentWidget()
        if current:
            # Check for specific minimum size, otherwise use sizeHint
            s = current.minimumSize()
            if s.isEmpty():
                s = current.minimumSize()
            return s
        return super().minimumSize()

    def sizeHint(self):
        current = self.currentWidget()
        if current:
            return current.sizeHint()
        return super().sizeHint()
