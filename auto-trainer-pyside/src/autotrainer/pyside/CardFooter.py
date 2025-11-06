from __future__ import annotations

from PySide6 import QtCore
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QSizePolicy


class CardFooter(QWidget):
    def __init__(self):
        super().__init__()
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("CardFooter")
        self.setStyleSheet("#CardFooter {background-color: #d9d9d9; padding: 16px; border-bottom-left-radius: 6px; border-bottom-right-radius: 6px}")
        self.setContentsMargins(0, 0, 0, 0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._layout = None

    def setContent(self, widget: QWidget):
        self._layout = QVBoxLayout()
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._layout.setContentsMargins(4, 2, 2, 4)
        self._layout.addWidget(widget)
        self.setLayout(self._layout)
