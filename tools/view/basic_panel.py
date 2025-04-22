from PySide6.QtWidgets import QWidget, QLabel, QHBoxLayout
from autotrainer.pyside import CardWidget


def create_panel(title, layout, status=None) -> QWidget:
    panel = CardWidget(header_background_color="#00b6de")

    layout.setContentsMargins(8, 8, 8, 8)
    layout.setSpacing(6)
    panel.setContentLayout(layout)

    header = QWidget()
    layout = QHBoxLayout()
    layout.setContentsMargins(0, 0, 0, 0)

    title = QLabel(title)
    title.setStyleSheet("font-weight: bold; color: white")
    layout.addWidget(title)
    layout.addStretch(1)

    if status is not None:
        layout.addWidget(status)

    header.setLayout(layout)
    panel.header.setContent(header)

    return panel
