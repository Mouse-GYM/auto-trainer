from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QFrame


class ATSeparator(QFrame):
    def __init__(self, color):
        super().__init__()

        self.setFrameShape(QFrame.HLine)

        self.set_color(color)

    def set_color(self, color):
        palette = self.palette()
        palette.setColor(QPalette.WindowText, color)
        self.setPalette(palette)
