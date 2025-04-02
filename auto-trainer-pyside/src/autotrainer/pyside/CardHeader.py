from PySide6 import QtCore
from PySide6.QtWidgets import QWidget, QVBoxLayout


class CardHeader(QWidget):
    def __init__(self, background_color: str = "#cfb87c"):
        super().__init__()

        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("CardHeader")
        self.setStyleSheet(
            "#CardHeader {background-color: " + background_color + \
            "; padding: 8px; border-top-left-radius: 6px; border-top-right-radius: 6px}")

        self._layout = None

    def setContent(self, widget: QWidget):
        self._layout = QVBoxLayout()
        self._layout.setContentsMargins(6, 4, 4, 6)
        self._layout.addWidget(widget)
        self.setLayout(self._layout)
