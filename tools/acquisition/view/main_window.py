import logging
import os
from pathlib import Path

from PySide6.QtCore import Qt, QCoreApplication
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import QMainWindow, QStatusBar, QToolBar, QLabel, QMessageBox, QApplication, QFileDialog, \
    QSizePolicy, QWidget, QComboBox
import qtawesome as qta

from autotrainer.core import EventManager
from tools.acquisition.model.app_model import AppModel
from tools.acquisition.model.user_preferences import UserPreferences
from tools.acquisition.view.main_content import MainContent
from tools.acquisition.view.preferences_dialog import PreferencesDialog

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, app: QApplication, user_preferences: UserPreferences, configuration: str = None,
                 app_version: str = "", is_dev: bool = False):
        super().__init__()

        self._app = app
        self._is_dev = is_dev

        self._preferences = user_preferences
        self._update_log_level(self._preferences.log_level)

        self._app_view_model = AppModel(self._preferences, app_version)

        self.setWindowTitle(f"Auto Trainer - Acquisition v{app_version}")

        self.main_content = MainContent(self._app_view_model)

        self.setContentsMargins(0, 0, 0, 0)

        self.setCentralWidget(self.main_content)

        self.centralWidget().layout().setContentsMargins(0, 0, 0, 0)

        self._create_actions()

        self._configure_menubar()

        self._configure_toolbar()

        self._configure_statusbar()

        # self.setWindowFlags(Qt.Dialog | Qt.MSWindowsFixedSizeDialogHint)

        self.setMaximumSize(1880, 1080)

        self._app_view_model.property_changed += self._app_model_property_changed

        self._app_view_model.on_error += self._show_error

        self._preferences.property_changed += self._preferences_property_changed

        if self._app_view_model.load_configuration(configuration or self._preferences.last_configuration):
            if configuration:
                self._preferences.last_configuration = configuration
            self._status_configuration.setText(self._preferences.last_configuration)

        self._reload_animals(self._app_view_model.animals)

    def on_capture_start_stop(self, is_toggled):
        if is_toggled:
            self.main_content.set_is_capture_active(True)
            self.edit_configuration_action.setEnabled(False)
            self.run_action.setEnabled(False)
            self._status_label.setText("Starting subprocesses...")
            logger.info("starting subprocesses")
            QCoreApplication.processEvents()
            if self._app_view_model.on_capture_start():
                self._status_label.setText("")
                icon = qta.icon('ei.stop')
                self.run_action.setText("Stop")
                self.run_action.setIcon(icon)
                self.run_action.setEnabled(True)
            else:
                self._status_label.setText("Startup failed")
                self.main_content.set_is_capture_active(False)
                self.edit_configuration_action.setEnabled(True)
                icon = qta.icon('ei.play')
                self.run_action.setChecked(False)
                self.run_action.setText("Start")
                self.run_action.setIcon(icon)
                self.run_action.setEnabled(True)
        else:
            self.run_action.setEnabled(False)
            self._status_label.setText("Stopping subprocesses...")
            logger.info("stopping subprocesses")
            QCoreApplication.processEvents()
            self._app_view_model.on_capture_stop()
            self.main_content.set_is_capture_active(False)
            self.edit_configuration_action.setEnabled(True)
            self._status_label.setText("")
            icon = qta.icon('ei.play')
            self.run_action.setText("Start")
            self.run_action.setIcon(icon)
            self.run_action.setEnabled(True)

    def on_activated(self):
        EventManager.create()
        self.main_content.on_activated()

    def closeEvent(self, event):
        self._app_view_model.on_close()

        event.accept()

    def moveEvent(self, e):
        self._preferences.last_window_x = self.pos().x()
        self._preferences.last_window_y = self.pos().y()

        super(MainWindow, self).moveEvent(e)

    def open_configuration(self):
        if self._preferences.last_configuration:
            location = os.path.dirname(os.path.realpath(self._preferences.last_configuration))
        else:
            location = str(Path.home())

        file_name, _ = QFileDialog.getOpenFileName(self, "Open Configuration", location, "Configuration Files (*.yaml)")

        if file_name and self._app_view_model.load_configuration(file_name):
            self._preferences.last_configuration = file_name

    def _save_configuration(self):
        file_name = self._preferences.last_configuration

        if not file_name:
            return self._save_configuration_as()

        self._app_view_model.save_configuration(file_name)

    def _save_configuration_as(self):
        file_name, _ = QFileDialog.getSaveFileName(self, "Save Configuration", "", "Configuration Files (*.yaml)")

        if file_name:
            if not file_name.endswith(".yaml"):
                file_name += ".yaml"

        if file_name and self._app_view_model.save_configuration(file_name):
            self._preferences.last_configuration = file_name

    def _edit_configuration(self):
        # isChecked() has already swapped to the new value by the time this is called
        if not self.edit_configuration_action.isChecked():
            self.main_content.set_is_editable(False)
            self.run_action.setEnabled(True)
        else:
            self.main_content.set_is_editable(True)
            self.run_action.setEnabled(False)

    def _show_preferences(self):
        dialog = PreferencesDialog(self._preferences)
        dialog.exec()

    def _create_actions(self):
        self.open_configuration_action = QAction(QIcon(qta.icon("fa5s.folder-open")), "Open Configuration...", self)
        self.open_configuration_action.setShortcut(QKeySequence(Qt.CTRL | Qt.Key_O))
        self.open_configuration_action.triggered.connect(self.open_configuration)

        self.save_configuration_action = QAction(QIcon(qta.icon("fa5s.save")), "Save Configuration", self)
        self.save_configuration_action.setShortcut(QKeySequence(Qt.CTRL | Qt.Key_S))
        self.save_configuration_action.triggered.connect(self._save_configuration)

        self.save_configuration_as_action = QAction("Save Configuration As...", self)
        self.save_configuration_as_action.triggered.connect(self._save_configuration_as)

        self.edit_configuration_action = QAction(QIcon(qta.icon("fa5s.edit")), "Edit Configuration", self)
        self.edit_configuration_action.setCheckable(True)
        self.edit_configuration_action.setChecked(False)
        self.edit_configuration_action.triggered.connect(self._edit_configuration)

        self.run_action = QAction(QIcon(qta.icon("ei.play")), "Start", self)
        self.run_action.setToolTip("Start or stop acquisition")
        self.run_action.setCheckable(True)
        self.run_action.setShortcut(QKeySequence(Qt.CTRL | Qt.Key_R))
        self.run_action.triggered.connect(self.on_capture_start_stop)

        self.view_diagnostics_action = QAction("Diagnostics", self)
        self.view_diagnostics_action.setToolTip("Show or hide diagnostics panel")
        self.view_diagnostics_action.setCheckable(True)
        self.view_diagnostics_action.setChecked(self.main_content.is_diagnostics_visible)
        self.view_diagnostics_action.triggered.connect(lambda: self._toggle_diagnostics_view())

        self.capture_trigger_action = QAction("Trigger Load Cell", self)
        self.capture_trigger_action.setCheckable(True)
        self.capture_trigger_action.triggered.connect(self._internal_simulate_trigger)

        self.force_detector_action = QAction("Trigger Force Detector", self)
        self.force_detector_action.setCheckable(True)
        self.force_detector_action.triggered.connect(self._internal_set_force_detector_seen)

        self.pellet_seen_action = QAction("Pellet Seen", self)
        self.pellet_seen_action.triggered.connect(self._internal_set_pellet_seen)

        self.mouse_seen_action = QAction("Mouse Seen", self)
        self.mouse_seen_action.triggered.connect(self._internal_set_mouse_seen)

        self.preferences_action = QAction(QIcon(qta.icon("fa5s.cog")), "Preferences", self)
        self.preferences_action.triggered.connect(lambda: self._show_preferences())

        self.quit_action = QAction("Quit")
        self.quit_action.setShortcut(QKeySequence(Qt.CTRL | Qt.Key_Q))
        self.quit_action.triggered.connect(lambda: self._app.quit())

    def _configure_menubar(self):
        menu_bar = self.menuBar()

        menu_bar.setObjectName("MenuBar")
        menu_bar.setStyleSheet("#MenuBar {background-color: #eee}")

        file_menu = menu_bar.addMenu("File")
        file_menu.addAction(self.open_configuration_action)
        file_menu.addSeparator()
        file_menu.addAction(self.save_configuration_action)
        file_menu.addAction(self.save_configuration_as_action)
        file_menu.addSeparator()
        file_menu.addAction(self.quit_action)

        view_menu = menu_bar.addMenu("View")
        view_menu.addAction(self.view_diagnostics_action)

    def _configure_toolbar(self):
        toolbar = QToolBar("Run Toolbar")
        toolbar.setFloatable(False)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        toolbar.addAction(self.run_action)

        toolbar.addSeparator()

        toolbar.addAction(self.edit_configuration_action)

        if self._is_dev:
            toolbar.addSeparator()
            toolbar.addAction(self.capture_trigger_action)
            toolbar.addAction(self.force_detector_action)
            toolbar.addAction(self.pellet_seen_action)
            toolbar.addAction(self.mouse_seen_action)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar.addWidget(spacer)

        toolbar.addWidget(QLabel("Subject:"))
        self._animal_dropdown = QComboBox()
        self._animal_dropdown.setMinimumWidth(200)
        self._animal_dropdown.setEditable(True)
        self._animal_dropdown.setDuplicatesEnabled(False)
        self._animal_dropdown.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._animal_dropdown.currentIndexChanged.connect(self._animal_changed)
        self._animal_dropdown.lineEdit().editingFinished.connect(self._add_animal)
        toolbar.addWidget(self._animal_dropdown)

        toolbar.addSeparator()

        toolbar.addAction(self.preferences_action)

    def _configure_statusbar(self):
        self._status_label = QLabel("")
        self._status_bar = QStatusBar(self)
        self._status_bar.addWidget(self._status_label)
        self._status_configuration = QLabel("")
        self._status_configuration.setContentsMargins(0, 0, 12, 0)
        self._status_bar.addPermanentWidget(self._status_configuration)
        self.setStatusBar(self._status_bar)

        self._status_bar.setSizeGripEnabled(False)

    def _toggle_diagnostics_view(self):
        self.main_content.set_diagnostics_visible(not self.main_content.is_diagnostics_visible)
        self.view_diagnostics_action.setChecked(self.main_content.is_diagnostics_visible)

    def _show_error(self, title: str, message: str):
        dlg = QMessageBox(self)
        dlg.setWindowTitle(title)
        dlg.setText(message)
        dlg.exec()

    def _preferences_property_changed(self, name, value, _):
        if name == "last_configuration":
            self._status_configuration.setText(value)
        elif name == "log_level":
            self._update_log_level(value)

    def _internal_simulate_trigger(self):
        self._app_view_model.behavior.trigger_tunnel(self.capture_trigger_action.isChecked())

    def _internal_set_force_detector_seen(self):
        new_value = self.force_detector_action.isChecked()
        self._app_view_model.head_fix.head_fix_reader.property_changed("is_force_detector_engaged", new_value,
                                                                       not new_value)

    def _internal_set_pellet_seen(self):
        self._app_view_model.behavior.algorithm.pellet_seen(True)

    def _internal_set_mouse_seen(self):
        self._app_view_model.behavior.algorithm.mouse_seen(True)

    def _add_animal(self):
        self._app_view_model.add_animal(self._animal_dropdown.currentText())

    def _animal_changed(self, index: int):
        if self._animal_dropdown.currentIndex() != -1:
            self._app_view_model.selected_animal = self._animal_dropdown.currentData()
        else:
            self._app_view_model.selected_animal = None

    def _app_model_property_changed(self, name: str, value, _old_value):
        if name == "animals":
            self._reload_animals(value)
        elif name == "selected_animal":
            if value is None:
                self._animal_dropdown.clear()
            else:
                index = self._animal_dropdown.findText(value.name)
                if index != -1:
                    self._animal_dropdown.setCurrentIndex(index)

    def _reload_animals(self, animals):
        self._animal_dropdown.clear()

        for animal in animals:
            self._animal_dropdown.addItem(animal.name, animal)

        if self._app_view_model.selected_animal is not None:
            index = self._animal_dropdown.findText(self._app_view_model.selected_animal.name)
            if index != -1:
                self._animal_dropdown.setCurrentIndex(index)
        else:
            self._animal_dropdown.setCurrentIndex(-1)

    @staticmethod
    def _update_log_level(value: int):
        logging.getLogger("tools").setLevel(value)
        logging.getLogger("autotrainer").setLevel(value)
        logging.getLogger("inference_algorithms").setLevel(value)

        if value == logging.DEBUG:
            logging.getLogger("transitions").setLevel(logging.INFO)
        else:
            logging.getLogger("transitions").setLevel(logging.WARNING)
