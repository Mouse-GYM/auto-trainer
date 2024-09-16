from PySide6.QtGui import Qt
from PySide6.QtWidgets import QWidget, QGroupBox, QVBoxLayout


class QSimpleGroupBox(QGroupBox):
    def __init__(self, title: str, widget: QWidget):
        super().__init__(title=title)

        h_layout = QVBoxLayout()
        h_layout.setContentsMargins(0, 0, 0, 0)
        h_layout.addWidget(widget)
        h_layout.addWidget(QWidget(), 1)
        self.setLayout(h_layout)

        self.setAlignment(Qt.AlignmentFlag.AlignTop)
