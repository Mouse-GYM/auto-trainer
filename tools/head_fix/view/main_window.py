from PySide6.QtCore import QSize
from PySide6.QtWidgets import QMainWindow, QStatusBar

from tools.head_fix.model.app_model import AppModel
from tools.head_fix.view.main_content import MainContent

from autotrainer.core import DeviceReader


class MainWindow(QMainWindow):
    def __init__(self, app_view_model: AppModel):
        super().__init__()

        self._app_view_model = app_view_model

        self.setWindowTitle("Head Fix")

        self.setMinimumSize(QSize(1300, 650))

        self.main_content = MainContent(app_view_model)

        self.setCentralWidget(self.main_content)

        self.setStatusBar(QStatusBar(self))

        self.main_content.connecting.connect(
            lambda: self.update_status("Head Fix Version: Waiting for response..."))

        self.main_content.disconnected.connect(lambda: self.update_status("Not connected"))

        self.update_status("Not connected")

        self._app_view_model.property_changed += self._model_property_changed

    def update_status(self, value: str):
        self.statusBar().showMessage(value)

    def on_activated(self):
        self._app_view_model.on_activated()
        self.main_content.on_activated()

    def closeEvent(self, event):
        self._app_view_model.on_close()

        event.accept()

    def _model_property_changed(self, name: str, value, _old_value):
        if name == DeviceReader.FIRMWARE_VERSION:
            self.update_status(f"Head Fix Version: {value}")
