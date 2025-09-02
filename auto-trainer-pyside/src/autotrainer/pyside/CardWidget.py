from __future__ import annotations

from typing import Optional

from PySide6 import QtCore
from PySide6.QtWidgets import QWidget, QGridLayout, QLayout

from .CardFooter import CardFooter
from .CardHeader import CardHeader

_DEFAULT_STYLE = "border-color: #ddd; border-width: 1px; border-style: solid; border-radius: 6px;"


class CardWidget(QWidget):
    def __init__(self, background_color: str = "white", title: str = "", header_background_color: Optional[str] = None,
                 content_layout: Optional[QLayout] = None, header_right_layout: Optional[QWidget | QLayout] = None):
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

        self._header = CardHeader(title=title, background_color=header_background_color)

        if header_right_layout is not None:
            self._header.setRightContent(header_right_layout)

        self._layout.addWidget(self._header, 0, 0)

        self._footer = CardFooter()
        self._layout.addWidget(self._footer, 2, 0)

        self.setLayout(self._layout)

        self._layout.setRowStretch(1, 1)

        if content_layout is not None:
            self.setContentLayout(content_layout)

        self._last_widget = None

    @property
    def header(self) -> CardHeader:
        return self._header

    @property
    def footer(self) -> CardFooter:
        return self._footer

    def setFooterVisible(self, visible: bool):
        self._footer.setVisible(visible)

    def setContentWidget(self, widget: Optional[QWidget]):
        if widget is not None:
            self._layout.addWidget(widget, 1, 0)
            # widget.setParent(self)  # not required, this is implicit with addWidget()

        last_w = self._last_widget
        if last_w is not None:
            self._layout.removeWidget(last_w)
            last_w.setParent(None)  # THIS IS REQUIRED,
            # otherwise the last widget will continue display itself on top of any other
            # not already selected previously.
            last_w.hide()
            last_w.update()  # force update to ensure widget is hidden

        self._last_widget = widget
        widget.show()
        self._layout.update()  # force update to ensure layout is refreshed

    def setContentLayout(self, layout: QLayout):
        self._layout.addLayout(layout, 1, 0)
