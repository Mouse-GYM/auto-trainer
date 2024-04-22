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

        self._app_view_model.measurements.version_ready.connect(lambda x: self.update_status(f"Head Fix Version: {x}"))

        self.main_content.connecting.connect(lambda: self.update_status("Head Fix Version: Waiting for response..."))

        self.main_content.disconnected.connect(lambda: self.update_status("Not connected"))

        self.update_status("Not connected")

    def update_status(self, value: str):
        self.statusBar().showMessage(value)

    def on_activated(self):
        self.main_content.on_activated()

    def closeEvent(self, event):
        self._app_view_model.on_close()

        event.accept()
