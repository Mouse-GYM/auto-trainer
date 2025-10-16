import logging
import threading
import time
from itertools import chain
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, QCoreApplication
from PySide6.QtGui import QAction, QIcon, QKeySequence, QPixmap, QColor
from PySide6.QtWidgets import (QMainWindow, QStatusBar, QToolBar, QLabel, QMessageBox, QApplication,
                               QSizePolicy, QWidget, QComboBox, QLineEdit, QDialog, QFileDialog, QPushButton)
import qtawesome as qta

from autotrainer.behavior import DiamondTriangleOffsetConfig, BehaviorAlgorithm
from autotrainer.behavior.behavior_algorithm import BehaviorAlgoProps
from autotrainer.core import EventManager, Offset3DTuple
from autotrainer.core.logging import get_console_handler, get_verbose_logger
from autotrainer.core.multiproc import make_daemon_timer, no_op_timer
from autotrainer.core.pose_elements import SceneElement
from autotrainer.inference import InferenceStatus, PoseResponse

from tools.acquisition.model.app_model import AppModel
from tools.acquisition.model.user_preferences import UserPreferences
from tools.acquisition.view.content_widget import InvokeMethod
from tools.acquisition.view.main_content import MainContent
from tools.acquisition.view.preferences_dialog import PreferencesDialog

logger = get_verbose_logger(__name__)

_calibrate_timer = make_daemon_timer

DEFAULT_DIAMOND_TRIANGLE_CALIB_DURATION = 3  # duration of calibration data acquisition
DEFAULT_DIAMOND_TRIANGLE_CALIB_TIMEOUT = 30  # maximum time before automated stop of calibration
# if not enough data is captured after that time the calib is automatically finished/stopped (and ask for retry)
DEFAULT_DIAMOND_TRIANGLE_NOISY_DISTANCE = 0.2  # distance over which data is considered noisy, and a retry proposed


#


class MainWindow(QMainWindow):
    def __init__(self, app: QApplication, user_preferences: UserPreferences, configuration: str = None,
                 app_version: str = "", is_dev: bool = False):
        super(MainWindow, self).__init__(None)

        self._app = app

        self._is_dev = is_dev

        self._preferences = user_preferences
        self._update_log_level(self._preferences.log_level)

        app_model = self._app_model = AppModel(self._preferences, app_version)

        self._title = f"Auto Trainer - Acquisition v{app_version}"

        self.setWindowTitle(self._title)

        self.main_content = MainContent(app_model)

        self.setContentsMargins(0, 0, 0, 0)
        self.setCentralWidget(self.main_content)
        self.centralWidget().layout().setContentsMargins(0, 0, 0, 0)

        self._create_actions()
        self._configure_menubar()
        self._configure_toolbar()
        self._configure_statusbar()

        self.setMaximumSize(1880, 1080)

        self._open_dialogs = []

        app_model.property_changed += self._app_model_property_changed
        app_model.on_error += self._show_error
        app_model.inference.property_changed += self._inference_property_changed
        user_preferences.property_changed += self._preferences_property_changed
        #
        app_model.load_configuration(configuration)
        self._reload_animals(self._app_model.animals)
        #


    def close(self):
        # explicitly close main content, reason is TextBoxHandler added to root logger handlers.
        self.main_content.close()
        super().close()

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
            if self._app_model.on_capture_start():
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
            self._app_model.on_capture_stop()
            self.main_content.set_is_capture_active(False)
            self.edit_configuration_action.setEnabled(True)
            self._status_label.setText("")
            icon = qta.icon('ei.play')
            self.run_action.setText("Start")
            self.run_action.setIcon(icon)
            self.run_action.setEnabled(True)

    @staticmethod
    def calculate_std_dev_manual(data):
        n = len(data)
        if n < 2:
            raise ValueError("Data must contain at least two values to calculate standard deviation.")

        mean = sum(data) / n
        squared_diffs = [(x - mean) ** 2 for x in data]
        variance = sum(squared_diffs) / (n - 1)  # Sample standard deviation
        std_dev = variance ** 0.5
        return mean, std_dev

    def _handle_calib_run(self, *, positions: List[Offset3DTuple], offsets: List[Offset3DTuple]):
        self._timer_calibrate.cancel()
        if len(offsets) < 3:
            self.calib_diamond_triangle_action.setEnabled(False)
            box = QMessageBox()
            box.setWindowTitle("Please")
            box.setText(
                "Could not get enough or data at all,\n"
                "please send pellet to make triangle visible in both cameras,\n"
                "then you can retry after.")
            box.setIcon(QMessageBox.Critical)
            self._open_dialogs.append(box)

            def remove():
                self.calib_diamond_triangle_action.setEnabled(True)
                # logger.debug("removing dialog from self.open_dialogs")
                try:
                    self._open_dialogs.remove(box)
                except ValueError:  # safer
                    pass

            retry_button = box.addButton("Retry calibration", QMessageBox.AcceptRole)
            retry_button.clicked.connect(lambda: self.on_calibrate_diamond_triangle(True))
            retry_button.clicked.connect(remove)
            #
            box.addButton("Cancel", QMessageBox.RejectRole).clicked.connect(remove)
            box.setWindowModality(Qt.NonModal)
            box.setModal(False)

            def close_event(event):
                remove()
                event.accept()

            box.closeEvent = close_event
            box.show()
            return
        avg_pos, stdev_pos = self.calculate_std_dev_manual(positions)
        assert isinstance(avg_pos, Offset3DTuple)
        assert isinstance(stdev_pos, Offset3DTuple)
        logger.info("position: average=%s stdev=%s", avg_pos, stdev_pos)
        avg_offset, stdev_offset = self.calculate_std_dev_manual(offsets)
        assert isinstance(avg_offset, Offset3DTuple)
        assert isinstance(stdev_offset, Offset3DTuple)
        logger.info("offset: average=%s stdev=%s", avg_offset, stdev_offset)
        noisy = False
        for val in chain(stdev_offset, stdev_pos):
            if val >= DEFAULT_DIAMOND_TRIANGLE_NOISY_DISTANCE:
                noisy = True
        if noisy:
            rsp = QMessageBox.warning(
                self, "Confirmation", f"The data is noisy, do you want retry longer ?",
                QMessageBox.Yes | QMessageBox.No
            )
            if rsp == QMessageBox.Yes:
                self._calib_run = self._make_calib_run(2 * DEFAULT_DIAMOND_TRIANGLE_CALIB_DURATION)
                self.on_calibrate_diamond_triangle(True)
            return
        app_model = self._app_model
        algo = app_model.behavior.algorithm
        current_save_path = save_path = algo.diamond_triangle_offset_config_path.expanduser()
        if save_path.exists():
            file_path: Optional[str] = None

            def retain_selected(path):
                nonlocal file_path
                file_path = path

            rsp = QMessageBox.question(
                self, "Confirmation",
                f"The configuration file ({save_path.as_posix()}) already exists, are you sure you want to proceed ?",
                QMessageBox.Yes | QMessageBox.No)
            if rsp != QMessageBox.Yes:
                return
            dialog = QFileDialog(self, "Save to configuration file", save_path.parent.as_posix(),
                                 "All yaml files (*.yaml *.yml)")
            dialog.selectFile(save_path.name)
            dialog.fileSelected.connect(retain_selected)
            dialog.exec()
            if file_path is None:
                return
            save_path = Path(file_path)

        else:
            QMessageBox.information(self, "Information",
                                    f"Successfully computed values for diamond-triangle position & offset.\n"
                                    f"\nSaving to {save_path.as_posix()}\n\n"
                                    f"If feature is enabled in configuration then values will be used and applied on "
                                    f"next sessions.",
                                    QMessageBox.Ok,
                                    )
        new_cfg = DiamondTriangleOffsetConfig(
            used_position=list(avg_pos),
            measured_offset=list(avg_offset),
        )
        logger.success("Saving new config to %s", save_path.as_posix())
        new_cfg.to_file(save_path)
        # if save_path == current_save_path:
        #    set to current algo _diamond_triangle_offset_config
        # is not needed, given it's read on each session start

    def _make_calib_run(self, calib_duration: float = DEFAULT_DIAMOND_TRIANGLE_CALIB_DURATION):
        logger.notice("Starting diamond-triangle calibration .. duration=%.1f second(s)", calib_duration)

        app_model = self._app_model
        algo = app_model.behavior.algorithm
        action = self.calib_diamond_triangle_action

        def record_offsets(pose_response: PoseResponse):
            nonlocal start_perf_c, offsets, positions, recording
            if not recording:
                return
            if len(offsets) > 2:
                self._timer_calibrate.cancel()
            new_offset = pose_response.get_parts_3d_offset(SceneElement.Diamond, SceneElement.Triangle)
            if new_offset is not None:
                offsets.append(new_offset)
                positions.append(app_model.hardware.last_position)
            if time.perf_counter() - start_perf_c > calib_duration:
                # required, to execute the function in the UI/main thread:
                # reminder this record_offsets is executed by some thread handler/worker in some callback
                InvokeMethod(self.on_calibrate_diamond_triangle, False)
                recording = False

        recording = True
        offsets = []
        positions = []
        action.setChecked(True)
        action.setIcon(qta.icon("fa5s.crosshairs", color='red'))
        before_pellet_delivery_enabled = algo.pellet_delivery_enabled
        algo.pellet_delivery_enabled = False
        start_perf_c = time.perf_counter()
        app_model.inference.pose_response_ready += record_offsets
        self._status_label.setText("Capturing data ..")
        timer = self._timer_calibrate = _calibrate_timer(
            DEFAULT_DIAMOND_TRIANGLE_CALIB_TIMEOUT,
            lambda: InvokeMethod(self.on_calibrate_diamond_triangle, False)
        )
        timer.start()
        # for i in range(15):
        #     offsets.append(Offset3DTuple(1 + 0.001 * i, 2 + 0.01 * i, 3 + 0.001 * i ** 2))
        #     positions.append(Offset3DTuple(1 + 0.001 * i, 2 + 0.01 * i, 3 + 0.1001 * i ** 2))
        #
        yield
        #
        self._status_label.setText("")
        logger.notice("finished diamond-triangle calibration")
        self._timer_calibrate.cancel()
        app_model.inference.pose_response_ready -= record_offsets
        algo.pellet_delivery_enabled = before_pellet_delivery_enabled
        action.setIcon(qta.icon("fa5s.crosshairs"))
        action.setChecked(False)
        #
        self._calib_run = None  # MUST be before
        self._handle_calib_run(positions=positions, offsets=offsets)

    def on_calibrate_diamond_triangle(self, is_toggled):
        if is_toggled and self._calib_run is None:
            self._calib_run = self._make_calib_run()
        calib_run = self._calib_run
        if is_toggled:
            # this triggers the execution of the first part of the calib run,
            # which is to record enough data
            next(calib_run)

        if not is_toggled:
            # this then triggers the stop of the data recording, and try to use it and if correct save it to file.
            try:
                next(calib_run)
            except StopIteration:
                pass

    def on_activated(self):
        EventManager.default()
        self.main_content.on_activated()

    def closeEvent(self, event):
        self._app_model.on_close()
        self._timer_calibrate.cancel()
        dialogs = self._open_dialogs
        self._open_dialogs = []
        for dialog in dialogs:
            dialog.close()
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
        dialog = PreferencesDialog(self._preferences, self._app_model)
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

        self._calib_run = None
        self._timer_calibrate = no_op_timer
        self.calib_diamond_triangle_action = QAction(QIcon(qta.icon("fa5s.crosshairs")), "Calibrate", self)
        self.calib_diamond_triangle_action.setToolTip("Calibrate diamond-triangle")
        self.calib_diamond_triangle_action.setCheckable(True)
        self.calib_diamond_triangle_action.triggered.connect(self.on_calibrate_diamond_triangle)
        self.calib_diamond_triangle_action.setEnabled(False)

        self.view_diagnostics_action = QAction("Diagnostics", self)
        self.view_diagnostics_action.setToolTip("Show or hide diagnostics panel")
        self.view_diagnostics_action.setCheckable(True)
        self.view_diagnostics_action.setChecked(self.main_content.is_diagnostics_visible)
        self.view_diagnostics_action.triggered.connect(lambda: self._toggle_diagnostics_view())

        self.capture_trigger_action = QAction("Load Cell", self)
        self.capture_trigger_action.setCheckable(True)
        self.capture_trigger_action.triggered.connect(self._internal_simulate_trigger)

        self.force_detector_action = QAction("Force Detector", self)
        self.force_detector_action.setCheckable(True)
        self.force_detector_action.triggered.connect(self._internal_set_force_detector_seen)

        self.pellet_seen_action = QAction("Pellet Seen", self)
        self.pellet_seen_action.triggered.connect(self._internal_set_pellet_seen)

        self.mouse_seen_action = QAction("Mouse Seen", self)
        self.mouse_seen_action.triggered.connect(self._internal_set_mouse_seen)

        self.mouse_near_pellet_action = QAction("Hands near pellet", self)
        self.mouse_near_pellet_action.triggered.connect(self._internal_mouse_near_pellet)

        self.preferences_action = QAction(QIcon(qta.icon("fa5s.cog")), "Preferences", self)
        self.preferences_action.triggered.connect(lambda: self._show_preferences())

        self.emergency_stop_action = QAction("Emergency Stop", self)
        self.emergency_stop_action.setCheckable(True)

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

        behavior = self._app_model.behavior
        analysis = behavior.analysis

        toolbar = QToolBar("Run Toolbar")
        toolbar.setFloatable(False)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        toolbar.addAction(self.run_action)
        toolbar.addSeparator()
        toolbar.addAction(self.edit_configuration_action)
        toolbar.addSeparator()
        toolbar.addAction(self.calib_diamond_triangle_action)

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
        self._notes.setMinimumWidth(300)
        self._notes.setText(self._app_model.notes)
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

        toolbar.addSeparator()

        emergency_button = QPushButton("Emergency Stop")
        emergency_button.setCheckable(True)
        emergency_button.setObjectName("EmergencyButton")
        emergency_button.setStyleSheet("#EmergencyButton {background-color: red; color: white; min-width: 100px}")

        def update_emergency_ui(is_toggled: bool, source: str):
            emergency_button.setText("Resume" if is_toggled else "Emergency Stop")
            self.setWindowTitle(f"{self._title} - BEHAVIOR ALGORITHM PAUSED - Source: {source}" if is_toggled else self._title)
            if source != "user-button":
                emergency_button.setChecked(is_toggled)

        def emergency_stop_triggered(is_toggled: bool):
            logger.verbose("emergency_stop_triggered: %s", is_toggled)
            (behavior.emergency_stop if is_toggled else behavior.emergency_resume)("user-button")

        emergency_button.toggled.connect(emergency_stop_triggered)
        behavior.emergency_stopped += lambda src: update_emergency_ui(True, source=src)
        behavior.emergency_resumed += lambda src: update_emergency_ui(False, source=src)

        toolbar.addWidget(emergency_button)

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
            self._app_model.behavior.algorithm.clean_raw_data_on_inactive_session = value

    def _internal_simulate_trigger(self):
        is_checked = self.capture_trigger_action.isChecked()
        load_cell_monitor = self._app_model.analysis.load_cell_monitor
        load_cell_monitor.force_engaged(is_checked)
        load_cell_monitor.is_engaged = is_checked

    def _internal_set_force_detector_seen(self):
        new_value = self.force_detector_action.isChecked()
        self._app_model.analysis.headbar_pressure_monitor.force_engaged(new_value)

    def _internal_set_pellet_seen(self):
        self._app_model.behavior.algorithm.pellet_seen(True)

    def _internal_set_mouse_seen(self):
        self._app_model.behavior.algorithm.mouse_seen(True)

    def _internal_mouse_near_pellet(self):
        behavior = self._app_model.behavior
        algo = behavior.algorithm
        uncover_dist = algo.pellet_hand_uncover_distance
        if uncover_dist is not None:
            new_val = uncover_dist - 0.1
            algo.pellet_hands_min_distance = new_val
            logger.debug("set pellet_hands_min_distance to %s", new_val)

    def notes_changed(self, value: str):
        self._app_model.notes = value

    def _add_animal(self):
        self._app_model.add_animal(self._animal_dropdown.currentText())

    def _animal_changed(self, index: int):
        if self._animal_dropdown.currentIndex() != -1:
            self._app_model.selected_animal = self._animal_dropdown.currentData()
        else:
            self._app_model.selected_animal = None

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
            self._preferences.selected_animal if self._app_model.selected_animal is None
            else self._app_model.selected_animal.name
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

    def _inference_property_changed(self, name: str, new_value, old_value):
        inference = self._app_model.inference
        if name == inference.STATUS:
            self.calib_diamond_triangle_action.setEnabled(new_value == InferenceStatus.live)
