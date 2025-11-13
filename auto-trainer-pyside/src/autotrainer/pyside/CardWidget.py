from __future__ import annotations

from typing import Optional

from PySide6 import QtCore
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QGridLayout, QLayout, QSizePolicy

from .CardFooter import CardFooter
from .CardHeader import CardHeader

_DEFAULT_STYLE = "border-color: #ddd; border-width: 1px; border-style: solid; border-radius: 6px;"


class CardWidget(QWidget):
    def __init__(self, background_color: str = "white", title: str = "", header_background_color: Optional[str] = None,
                 content_layout: Optional[QLayout] = None, header_right_layout: Optional[QWidget | QLayout] = None):
        super().__init__()

        self.setContentsMargins(0, 0, 0, 0)

        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("CardWidget")

        style = _DEFAULT_STYLE

        if background_color is not None:
            style = f"background-color: {background_color}; {style}"

        self.setStyleSheet(f"#CardWidget {{{style}}}")

        self._layout = QGridLayout()
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        self._header = CardHeader(title=title, background_color=header_background_color)

        if header_right_layout is not None:
            self._header.setRightContent(header_right_layout)

        self._layout.addWidget(self._header, 0, 0)

        self._footer = CardFooter()
        self._layout.addWidget(self._footer, 2, 0)

        self.setLayout(self._layout)

        self._last_widget_or_layout = None

        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        if content_layout is not None:
            self.setContentLayout(content_layout)

    @property
    def header(self) -> CardHeader:
        return self._header

    @property
    def footer(self) -> CardFooter:
        return self._footer

    def setFooterVisible(self, visible: bool):
        self._footer.setVisible(visible)

    def setContentWidget(self, widget: Optional[QWidget]):
        last_w_or_l = self._last_widget_or_layout
        if last_w_or_l is not None:
            self._layout.removeWidget(last_w_or_l)
            last_w_or_l.setParent(None)  # THIS IS REQUIRED,
            # otherwise the last widget will continue display itself on top of any other
            # already selected previously.
            last_w_or_l.hide()
            last_w_or_l.update()  # force update to ensure widget is hidden

        if widget is not None:
            self._layout.addWidget(widget, 1, 0)
            # self.setSizePolicy(widget.sizePolicy())
            # widget.setParent(self)  # not required, this is implicit with addWidget()

        self._last_widget_or_layout = widget
        widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self._layout.update()  # force update to ensure layout is refreshed

    def setContentLayout(self, layout: QLayout):
        last = self._last_widget_or_layout
        if last is not None:
            if isinstance(last, QWidget):
                self._layout.removeWidget(last)
            else:
                self._layout.removeItem(last)
        self._layout.addLayout(layout, 1, 0)
        self._last_widget_or_layout = layout
        self._layout.update()  # force update to ensure layout is refreshed
