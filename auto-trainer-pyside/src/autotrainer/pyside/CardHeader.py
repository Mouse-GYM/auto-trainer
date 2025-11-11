from __future__ import annotations

from typing import Optional

from PySide6 import QtCore
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLayout, QSizePolicy


class CardHeader(QWidget):
    DEFAULT_BACKGROUND_COLOR = "#00b6de"
    DEFAULT_TITLE_COLOR = "white"

    def __init__(self, title: str = "", background_color: Optional[str] = None, title_color: Optional[str] = None):
        super().__init__()
        self.setContentsMargins(0, 0, 0, 0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        if background_color is None:
            background_color = CardHeader.DEFAULT_BACKGROUND_COLOR

        if title_color is None:
            title_color = CardHeader.DEFAULT_TITLE_COLOR

        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("CardHeader")
        self.setStyleSheet(
            "#CardHeader {background-color: " + background_color + \
            "; padding: 8px; border-top-left-radius: 6px; border-top-right-radius: 6px}")

        self._layout = QHBoxLayout(self)
        # self.setLayout(self._layout)
        self._layout.setContentsMargins(6, 4, 4, 6)

        self._title_label = QLabel(f"<b>{title}</b>")
        if title_color is not None:
            self._title_label.setStyleSheet(f"color: {title_color}")
        self._layout.addWidget(self._title_label)

        self._right_content: Optional[QWidget, QLayout] = None


    def setTitle(self, title: str, color: Optional[str] = None):
        title = f"<b>{title}</b>"
        self._title_label.setText(title)
        if color is not None:
            self._title_label.setStyleSheet(f"color: {color}")

    def setRightContent(self, content: Optional[QWidget | QLayout] = None):
        prev = self._right_content
        if prev is not None:
            self._layout.removeWidget(prev)
            prev.setParent(None)  # required

        if content is not None:
            self._right_content = content
            if isinstance(content, QWidget):
                self._layout.addWidget(content, 0, Qt.AlignmentFlag.AlignRight)
            else:
                self._layout.addLayout(content, 0)
                content.setAlignment(Qt.AlignmentFlag.AlignRight)

    def setContent(self, widget: QWidget):
        self._layout = QVBoxLayout()
        # self._layout.setContentsMargins(6, 4, 4, 6)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addWidget(widget)
        self.setLayout(self._layout)
