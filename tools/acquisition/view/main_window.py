import logging

from PySide6.QtCore import Qt, QCoreApplication
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import QMainWindow, QStatusBar, QToolBar, QLabel
import qtawesome as qta

from tools.acquisition.model.app_model import AppModel
from tools.acquisition.view.main_content import MainContent

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, app_view_model: AppModel):
        super().__init__()

        self._app_view_model = app_view_model

        self.setWindowTitle("Auto Trainer - Acquisition")

        self.main_content = MainContent(app_view_model)

        self.setCentralWidget(self.main_content)

        self.centralWidget().layout().setContentsMargins(0, 0, 0, 0)

        toolbar = QToolBar("Run Toolbar")
        toolbar.setFloatable(False)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self.button_action = QAction(QIcon(qta.icon('ei.play')), "Start", self)
        self.button_action.setToolTip("Start or stop acquisition")
        self.button_action.setCheckable(True)
        self.button_action.setShortcut(QKeySequence(Qt.CTRL | Qt.Key_R))
        self.button_action.triggered.connect(self.on_capture_start_stop)
        toolbar.addAction(self.button_action)

        toolbar.addSeparator()

        self.trigger_action = QAction(QIcon(qta.icon('fa5s.wave-square')), "Trigger", self)
        self.trigger_action.setToolTip("Send simulated recording trigger")
        self.trigger_action.setCheckable(False)
        self.trigger_action.setEnabled(False)
        self.trigger_action.setShortcut(QKeySequence(Qt.CTRL | Qt.Key_T))
        self.trigger_action.triggered.connect(lambda: self._app_view_model.toggle_trigger_state())
        toolbar.addAction(self.trigger_action)

        self.preferences_action = QAction(QIcon(qta.icon('fa5s.cog')), "Preferences", self)
        # toolbar.addAction(self.preferences_action)

        self._status_label = QLabel("")
        self._status_bar = QStatusBar(self)
        self._status_bar.addWidget(self._status_label)
        self.setStatusBar(self._status_bar)

    def on_capture_start_stop(self, is_toggled):
        if is_toggled:
            self.main_content.setCaptureEnabled(False)
            self.button_action.setEnabled(False)
            self._status_label.setText("Starting subprocesses...")
            logger.info("starting subprocesses")
            QCoreApplication.processEvents()
            if self._app_view_model.on_capture_start():
                self._status_label.setText("")
                icon = qta.icon('ei.stop')
                self.button_action.setText("Stop")
                self.button_action.setIcon(icon)
                self.button_action.setEnabled(True)
                self.trigger_action.setEnabled(True)
            else:
                self._status_label.setText("Startup failed")
                icon = qta.icon('ei.play')
                self.button_action.setChecked(False)
                self.button_action.setText("Start")
                self.button_action.setIcon(icon)
                self.button_action.setEnabled(True)
                self.trigger_action.setEnabled(False)
        else:
            self.main_content.setCaptureEnabled(True)
            self.button_action.setEnabled(False)
            self._status_label.setText("Stopping subprocesses...")
            logger.info("stopping subprocesses")
            QCoreApplication.processEvents()
            self._app_view_model.on_capture_stop()
            self._status_label.setText("")
            icon = qta.icon('ei.play')
            self.button_action.setText("Start")
            self.button_action.setIcon(icon)
            self.button_action.setEnabled(True)
            self.trigger_action.setEnabled(False)

    def on_activated(self):
        self.main_content.on_activated()
        self._app_view_model.on_activated()

    def closeEvent(self, event):
        self._app_view_model.on_close()

        event.accept()
