from __future__ import annotations

from typing import Optional

from PySide6 import QtCore
from PySide6.QtWidgets import QWidget, QGridLayout, QLayout

from .CardFooter import CardFooter
from .CardHeader import CardHeader

_DEFAULT_STYLE = "border-color: #ddd; border-width: 1px; border-style: solid; border-radius: 6px;"


class CardWidget(QWidget):
    def __init__(self, background_color: Optional[str] = "white", header_background_color: str = "#cfb87c"):
        super().__init__()

        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("CardWidget")

        style = _DEFAULT_STYLE

        if background_color is not None:
            style = f"background-color: {background_color}; {style}"

        self.setStyleSheet(f"#CardWidget {{{style}}}")

        self._layout = QGridLayout()
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        self._header = CardHeader(background_color=header_background_color)
        self._layout.addWidget(self._header, 0, 0)

        self._footer = CardFooter()
        self._layout.addWidget(self._footer, 2, 0)

        self.setLayout(self._layout)

        self._layout.setRowStretch(1, 1)

        self._last_widget = None

    @property
    def header(self) -> CardHeader:
        return self._header

    @property
    def footer(self) -> CardFooter:
        return self._footer

    def setFooterVisible(self, visible: bool):
        self._footer.setVisible(visible)

    def setContentWidget(self, widget: QWidget | None):
        if self._last_widget is not None:
            self._layout.removeWidget(self._last_widget)

        if widget is not None:
            self._layout.addWidget(widget, 1, 0)

        self._last_widget = widget

    def setContentLayout(self, layout: QLayout):
        self._layout.addLayout(layout, 1, 0)
