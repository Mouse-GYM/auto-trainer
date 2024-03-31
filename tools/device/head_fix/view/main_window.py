from PySide6.QtCore import QSize
from PySide6.QtWidgets import QMainWindow, QStatusBar

from tools.device.head_fix.model.app_model import AppModel
from tools.device.head_fix.view.main_content import MainContent


class MainWindow(QMainWindow):
    def __init__(self, app_view_model: AppModel):
        super().__init__()

        self._app_view_model = app_view_model

        self.setWindowTitle("Head Fix")

        self.setMinimumSize(QSize(640, 480))

        self.main_content = MainContent(app_view_model)

        self.setCentralWidget(self.main_content)

        self.setStatusBar(QStatusBar(self))

    def on_activated(self):
        self.main_content.on_activated()

    def closeEvent(self, event):
        self._app_view_model.on_close()

        event.accept()
