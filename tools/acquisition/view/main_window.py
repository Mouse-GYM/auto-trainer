import logging

from PySide6.QtCore import Qt, QCoreApplication
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import QMainWindow, QStatusBar, QToolBar, QLabel, QMessageBox, QApplication, \
    QSizePolicy, QWidget, QComboBox, QLineEdit
import qtawesome as qta

from autotrainer.core import EventManager
from autotrainer.core.logging import get_console_handler
from tools.acquisition.model.app_model import AppModel
from tools.acquisition.model.user_preferences import UserPreferences
from tools.acquisition.view.main_content import MainContent
from tools.acquisition.view.preferences_dialog import PreferencesDialog

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, app: QApplication, user_preferences: UserPreferences, configuration: str = None,
                 app_version: str = "", is_dev: bool = False):
        super(MainWindow, self).__init__(None)

        self._app = app

        self._is_dev = is_dev

        self._preferences = user_preferences
        self._update_log_level(self._preferences.log_level)

        self._model = AppModel(self._preferences, app_version)

        self.setWindowTitle(f"Auto Trainer - Acquisition v{app_version}")

        self.main_content = MainContent(self._model)

        self.setContentsMargins(0, 0, 0, 0)

        self.setCentralWidget(self.main_content)

        self.centralWidget().layout().setContentsMargins(0, 0, 0, 0)

        self._create_actions()

        self._configure_menubar()

        self._configure_toolbar()

        self._configure_statusbar()

        self.setMaximumSize(1880, 1080)

        self._model.property_changed += self._app_model_property_changed

        self._model.on_error += self._show_error

        self._preferences.property_changed += self._preferences_property_changed

        self._model.load_configuration(configuration)

        self._reload_animals(self._model.animals)

    def on_capture_start_stop(self, is_toggled):
        if is_toggled:
            self.main_content.set_is_capture_active(True)
            self.edit_configuration_action.setEnabled(False)
            self.run_action.setEnabled(False)
            self._status_label.setText("Starting subprocesses...")
            logger.info("starting subprocesses")
            QCoreApplication.processEvents()
            # This call should not really happen on the UI thread (takes too long).  Above hack to ensure UI elements
            # update.
            if self._model.on_capture_start():
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
            # This call should not really happen on the UI thread (takes too long).  Above hack to ensure UI elements
            # update.
            self._model.on_capture_stop()
            self.main_content.set_is_capture_active(False)
            self.edit_configuration_action.setEnabled(True)
            self._status_label.setText("")
            icon = qta.icon('ei.play')
            self.run_action.setText("Start")
            self.run_action.setIcon(icon)
            self.run_action.setEnabled(True)

    def on_activated(self):
        EventManager.default()
        self.main_content.on_activated()

    def closeEvent(self, event):
        self._model.on_close()
        event.accept()

    def moveEvent(self, e):
        self._preferences.last_window_x = self.pos().x()
        self._preferences.last_window_y = self.pos().y()

        super(MainWindow, self).moveEvent(e)

    def _edit_configuration(self):
        # isChecked() has already swapped to the new value by the time this is called
        if not self.edit_configuration_action.isChecked():
            self.main_content.set_is_editable(False)
            self.run_action.setEnabled(True)
        else:
            self.main_content.set_is_editable(True)
            self.run_action.setEnabled(False)

    def _show_preferences(self):
        dialog = PreferencesDialog(self._preferences, self._model)
        dialog.exec()

    def _create_actions(self):
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

        self.mouse_near_pellet_action = QAction("Hands near pellet", self)
        self.mouse_near_pellet_action.setCheckable(True)
        self.mouse_near_pellet_action.triggered.connect(self._internal_mouse_near_pellet)

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
            toolbar.addAction(self.mouse_near_pellet_action)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar.addWidget(spacer)

        toolbar.addWidget(QLabel("Notes:"))
        self._notes = QLineEdit()
        self._notes.setMinimumWidth(400)
        self._notes.setText(self._model.notes)
        self._notes.textChanged.connect(self.notes_changed)
        self._notes.setContentsMargins(4, 0, 8, 0)
        toolbar.addWidget(self._notes)

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
        if name == "log_level":
            self._update_log_level(value)
        elif name == "remove_raw_data_when_inactive_session":
            self._model.behavior.algorithm.clean_raw_data_on_inactive_session = value

    def _internal_simulate_trigger(self):
        is_checked = self.capture_trigger_action.isChecked()
        self._model.analysis.load_cell_monitor.force_engaged(is_checked)

    def _internal_set_force_detector_seen(self):
        new_value = self.force_detector_action.isChecked()
        self._model.analysis.headbar_pressure_monitor.force_engaged(new_value)

    def _internal_set_pellet_seen(self):
        self._model.behavior.algorithm.pellet_seen(True)

    def _internal_set_mouse_seen(self):
        self._model.behavior.algorithm.mouse_seen(True)

    def _internal_mouse_near_pellet(self):
        behavior = self._model.behavior
        algo = behavior.algorithm
        if self.mouse_near_pellet_action.isChecked():
            algo.pellet_hand_uncover_distance = None
        else:
            cfg = self._model.loaded_configuration
            algo.pellet_hand_uncover_distance = cfg.behavior.pellet_delivery.pellet_hand_uncover_distance
        logger.debug("set pellet_hand_uncover_distance to %s", algo.pellet_hand_uncover_distance)

    def notes_changed(self, value: str):
        self._model.notes = value

    def _add_animal(self):
        self._model.add_animal(self._animal_dropdown.currentText())

    def _animal_changed(self, index: int):
        if self._animal_dropdown.currentIndex() != -1:
            self._model.selected_animal = self._animal_dropdown.currentData()
        else:
            self._model.selected_animal = None

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

        # get current selected animal before adding them,
        # given when adding that's modifying the currently selected one too,
        # which reset the preference selected to that one...
        find_animal_name = (
            self._preferences.selected_animal if self._model.selected_animal is None
            else self._model.selected_animal.name
        )

        for animal in animals:
            self._animal_dropdown.addItem(animal.name, animal)

        if find_animal_name is not None:
            index = self._animal_dropdown.findText(find_animal_name)
            if index != -1:
                self._animal_dropdown.setCurrentIndex(index)
        else:
            self._animal_dropdown.setCurrentIndex(-1)

    @staticmethod
    def _update_log_level(value: int):
        # controlled via console and file handlers now
        get_console_handler().setLevel(value)
        # logging.getLogger("tools").setLevel(value)
        # logging.getLogger("autotrainer").setLevel(value)
        # logging.getLogger("inference_algorithms").setLevel(value)
        #
        # if value == logging.DEBUG:
        #     logging.getLogger("transitions").setLevel(logging.INFO)
        # else:
        #     logging.getLogger("transitions").setLevel(logging.WARNING)
