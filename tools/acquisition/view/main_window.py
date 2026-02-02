import collections
import dataclasses
import math
import shutil
import threading
import time
from datetime import datetime
from functools import partial
from itertools import chain
from pathlib import Path
from typing import List, Optional, Dict

from PySide6.QtCore import Qt, QCoreApplication, Signal, QSize
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (QMainWindow, QStatusBar, QToolBar, QLabel, QMessageBox, QApplication,
                               QSizePolicy, QWidget, QComboBox, QLineEdit, QFileDialog, QPushButton, QHBoxLayout,
                               QSpinBox, QDoubleSpinBox)
import qtawesome as qta

from autotrainer.core import EventManager, Offset3DTuple, AnimalSubject, SystemConfiguration, CameraConfiguration, \
    calculate_std_dev_manual
from autotrainer.core.configuration import DEFAULT_3D_CALIB_DIR_NAME
from autotrainer.core.logging import get_console_handler, get_verbose_logger
from autotrainer.core.multiproc import make_daemon_timer, no_op_timer
from autotrainer.core.pose_elements import SceneElement
from autotrainer.core.event.api_event_kind import ApiEventKind
from autotrainer.core.project.project_info import DATE_TIME_FORMAT

from autotrainer.inference import InferenceStatus, PoseResponse

from autotrainer.behavior import TrainingMode
from autotrainer.core.diamond_triangle_config import DiamondTriangleOffsetConfig
from autotrainer.behavior.behavior_algorithm import BehaviorAlgoProps
from autotrainer.inference.analysis import IntersessionResponse
from autotrainer.pyside.content_widget import InvokeMethod

from autotrainer.training import TrainingPlan

from tools.acquisition.model.app_model import AppModel, AppModelStatus
from tools.acquisition.model.handle_3d_calibration import make_3d_calib
from tools.acquisition.model.inference_model import InferenceModel
from tools.acquisition.model.training_plan import get_plan_id
from tools.acquisition.model.user_preferences import UserPreferences
from tools.acquisition.view.main_content import MainContent
from tools.acquisition.view.preferences_dialog import PreferencesDialog

logger = get_verbose_logger(__name__)

_calibrate_timer = make_daemon_timer

DEFAULT_DIAMOND_TRIANGLE_CALIB_DURATION = 3  # duration of calibration data acquisition
DEFAULT_DIAMOND_TRIANGLE_CALIB_TIMEOUT = 30  # maximum time before automated stop of calibration
# if not enough data is captured after that time the calib is automatically finished/stopped (and ask for retry)
DEFAULT_DIAMOND_TRIANGLE_NOISY_DISTANCE = 0.2  # distance over which data is considered noisy, and a retry proposed


class MainWindow(QMainWindow):

    training_mode_changed = Signal(TrainingMode)
    running_status_changed = Signal(bool)  # True == running

    def __init__(
        self,
        app: QApplication,
        user_preferences: UserPreferences,
        configuration: str = None,
        app_version: str = "",
        is_dev: bool = False,
    ):
        super().__init__(None)

        self._default_event_manager = EventManager.default()
        self._post_api_event = self._default_event_manager.post_event_content

        self._orig_inference_analysis_feed = None
        self._orig_inference_analysis_process = None

        self._app = app
        self._is_dev = is_dev
        self._preferences = user_preferences
        self._update_log_level(self._preferences.log_level)
        self._title = f"Auto Trainer - Acquisition v{app_version}"
        self._closing = False
        self._close_event = None
        self._start_capture_thread = None
        self._stop_capture_thread = None

        self.setWindowTitle(self._title)

        self._open_dialogs = []
        self._training_plan_index_by_plan_id: Dict[Optional[str], int] = {}
        self._diamond_triangle_calib_run = None

        app_model = self._app_model = AppModel(self._preferences, app_version)

        try:
            self.setContentsMargins(0, 0, 0, 0)

            self.main_content = MainContent(app_model)

            self._create_actions()
            self._configure_menubar()
            self._configure_toolbar()
            self._configure_statusbar()

            self.setCentralWidget(self.main_content)
            self.centralWidget().layout().setContentsMargins(0, 0, 0, 0)
            # self.setMaximumSize(1880, 1080)
        except Exception as err:
            app_model.on_close()
            raise RuntimeError(f"Error setting up UI: {err}") from err

        app_model.configuration_loaded_event += self._on_app_model_configuration_loaded
        try:
            app_model.load_configuration(configuration)
        except Exception as err:
            app_model.on_close()
            raise RuntimeError(f"Could not load config: {err}") from err

        app_model.property_changed += self._app_model_property_changed
        app_model.on_error += self._show_error
        app_model.inference.property_changed += self._inference_property_changed
        # app_model.behavior.algorithm.property_changed += self._behavior_algo_property_changed
        user_preferences.property_changed += self._preferences_property_changed
        self.running_status_changed.connect(self._set_start_or_stop)
        #
        self._reload_animals(self._app_model.animals)


    @property
    def app_model(self) -> AppModel:
        return self._app_model

    def _add_box_to_open_dialogs(self, box: QMessageBox):
        self._open_dialogs.append(box)
        def close_event(event, orig_close_event=box.closeEvent):
            try:
                self._open_dialogs.remove(box)
            except ValueError:
                pass
            orig_close_event(event)
            event.accept()
        box.closeEvent = close_event

    def _set_start_or_stop(self, started: bool):
        self.main_content.set_is_capture_active(started)
        #
        stopped = not started
        self._animal_dropdown.setEnabled(stopped)
        self._training_plan_combo.setEnabled(stopped)
        self.edit_camera_settings_action.setEnabled(stopped)
        self.make_3d_calib_action.setEnabled(stopped)
        #
        run_action = self.run_action
        run_action.blockSignals(True)  # block signal to ensure we don't re-start/stop
        run_action.setChecked(started)
        run_action.blockSignals(False)
        if started:
            icon = qta.icon('ei.stop')
            run_action.setText("Stop")
            run_action.setIcon(icon)
        else:
            icon = qta.icon('ei.play')
            run_action.setText("Start")
            run_action.setIcon(icon)

    def on_capture_start_stop(self, is_toggled):
        app_model = self._app_model
        self.run_action.setEnabled(False)
        self.make_3d_calib_action.setEnabled(False)
        self.running_status_changed.emit(is_toggled)
        if is_toggled:
            self._status_label.setText("Starting acquisition...")
            def exec_start_capture(prev_thread=self._start_capture_thread):
                if prev_thread is not None:
                    logger.verbose("joining previous start thread")
                    prev_thread.join()
                logger.info("starting subprocesses")
                try:
                    started = app_model.on_capture_start()
                except Exception as err:
                    logger.exception("app_model.on_capture_start failed: %s", err)
                    started = False
                if started:
                    self._status_label.setText("")
                    self._acquisition_started = True
                    self._check_diamond_triangle_config()
                else:
                    self._status_label.setText("Startup failed")
                    self.running_status_changed.emit(False)
                self.run_action.setEnabled(True)
                self._start_capture_thread = None
            thread = threading.Thread(target=exec_start_capture, daemon=True)
            self._start_capture_thread = thread
            thread.start()
        else:
            self._status_label.setText("Stopping acquisition...")
            def exec_stop_capture(prev_start=self._start_capture_thread,
                                  prev_stop=self._stop_capture_thread):
                if prev_start is not None:
                    logger.verbose("joining previous start thread")
                    prev_start.join()
                logger.info("stopping subprocesses")
                app_model.on_capture_stop()
                self.running_status_changed.emit(False)
                self.run_action.setEnabled(True)
                self._status_label.setText("")
                self._acquisition_started = False
            thread = threading.Thread(target=exec_stop_capture, daemon=True)
            self._stop_capture_thread = thread
            thread.start()

    def on_previous_plan_phase(self):
        app_model = self._app_model
        plan = app_model.attached_plan
        if plan is None:
            return
        logger.info("fallback on plan %s (%s)", plan.plan_id, hex(id(plan)))
        plan.fallback()
        self._refresh_prev_next_phases()
        self.main_content.training_plan_changed.emit(plan)

    def on_next_plan_phase(self):
        app_model = self._app_model
        plan = app_model.attached_plan
        if plan is None:
            return
        logger.info("advance on plan %s (%s)", plan.plan_id, hex(id(plan)))
        plan.advance()
        self._refresh_prev_next_phases()
        self.main_content.training_plan_changed.emit(plan)

    def _handle_diamond_triangle_calib_run(
        self,
        *,
        positions: List[Offset3DTuple],  # motor coordinate system positions
        offsets: List[Offset3DTuple],  # diamond-triangle offsets (inference coordinate system)
        diamond_locs3d: List[Offset3DTuple],  # diamond loc3d (inference coordinate system)
    ):
        self._timer_calibrate_diamond_triangle.cancel()
        if len(offsets) < 3 or len(diamond_locs3d) < 10:
            self.calib_diamond_triangle_action.setEnabled(False)
            box = QMessageBox()
            box.setWindowTitle("Please")
            box.setText(
                "Could not get enough or data at all,\n"
                "please send pellet to make triangle visible in both cameras,\n"
                "then you can retry after.")
            box.setIcon(QMessageBox.Icon.Critical)

            self._open_dialogs.append(box)

            def remove():
                self.calib_diamond_triangle_action.setEnabled(True)
                # logger.debug("removing dialog from self.open_dialogs")
                try:
                    self._open_dialogs.remove(box)
                except ValueError:  # safer
                    pass

            retry_button = box.addButton("Retry calibration", QMessageBox.ButtonRole.AcceptRole)
            retry_button.clicked.connect(lambda: self.on_calibrate_diamond_triangle(True))
            retry_button.clicked.connect(remove)
            #
            box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole).clicked.connect(remove)
            box.setWindowModality(Qt.WindowModality.NonModal)
            box.setModal(False)

            def close_event(event):
                remove()
                event.accept()

            box.closeEvent = close_event
            box.show()
            return
        #
        avg_pos, stdev_pos = calculate_std_dev_manual(positions)
        assert isinstance(avg_pos, Offset3DTuple)
        assert isinstance(stdev_pos, Offset3DTuple)
        logger.info("motor-position: avg=%s stdev=%s", avg_pos, stdev_pos)
        #
        avg_offset, stdev_offset = calculate_std_dev_manual(offsets)
        assert isinstance(avg_offset, Offset3DTuple)
        assert isinstance(stdev_offset, Offset3DTuple)
        logger.info("diamond-triangle-inference-offset: avg=%s stdev=%s", avg_offset, stdev_offset)
        #
        avg_dia_loc3, stdev_dia_loc3d = calculate_std_dev_manual(diamond_locs3d)
        assert isinstance(avg_dia_loc3, Offset3DTuple)
        assert isinstance(stdev_dia_loc3d, Offset3DTuple)
        logger.info("diamond-inference-position: avg=%s stdev=%s", avg_dia_loc3, stdev_dia_loc3d)
        #
        noisy = False
        for val in chain(stdev_offset, stdev_pos, stdev_dia_loc3d):
            if val >= DEFAULT_DIAMOND_TRIANGLE_NOISY_DISTANCE:
                noisy = True
        if noisy:
            rsp = QMessageBox.warning(
                self, "Confirmation", f"The data is noisy, do you want retry longer ?",
                QMessageBox.Yes | QMessageBox.No
            )
            if rsp == QMessageBox.Yes:
                self._diamond_triangle_calib_run = self._make_diamond_triangle_calib_run(2 * DEFAULT_DIAMOND_TRIANGLE_CALIB_DURATION)
                self.on_calibrate_diamond_triangle(True)
            return
        app_model = self._app_model
        algo = app_model.behavior.algorithm
        save_path = algo.diamond_triangle_offset_config_path.expanduser()
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

        # always:
        QMessageBox.information(self, "Information",
                                f"Successfully computed values for diamond-triangle position & offset.\n"
                                f"\nSaving to {save_path.as_posix()}\n\n"
                                f"Calibration is being used immediately by now.",
                                QMessageBox.Ok,
                                )
        new_cfg = DiamondTriangleOffsetConfig(
            used_position=avg_pos,
            measured_offset=avg_offset,
            diamond_coord=avg_dia_loc3,
        )
        logger.success("Saving new config %s to %s", new_cfg, save_path.as_posix())
        new_cfg.to_file(save_path)
        #
        app_model = self._app_model
        algo = app_model.behavior.algorithm
        algo.diamond_triangle_config = new_cfg
        animal = app_model.selected_animal
        # to ensure animal will gets its x/y/z in DCS
        app_model.selected_animal = None
        app_model.selected_animal = animal

    def _make_diamond_triangle_calib_run(self, calib_duration: float = DEFAULT_DIAMOND_TRIANGLE_CALIB_DURATION):
        logger.notice("Starting diamond-triangle calibration .. duration=%.1f second(s)", calib_duration)

        self._post_api_event(ApiEventKind.calibrationDcsStarted)

        app_model = self._app_model
        app_model.status = AppModelStatus.CALIBRATION_DCS

        algo = app_model.behavior.algorithm
        action = self.calib_diamond_triangle_action

        diamond_locs3d = []

        def record_offsets(pose_response: PoseResponse):
            nonlocal start_perf_c, offsets, positions, recording
            if not recording:
                return
            if len(offsets) > 2:
                self._timer_calibrate_diamond_triangle.cancel()
            new_offset = pose_response.get_parts_3d_offset(SceneElement.Diamond, SceneElement.Triangle)
            if new_offset is not None:
                offsets.append(new_offset)
                positions.append(app_model.hardware.last_position)
            dia_loc3d = pose_response.locations_3d.get(SceneElement.Diamond)
            if dia_loc3d is not None:
                diamond_locs3d.append(dia_loc3d)
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
        timer = self._timer_calibrate_diamond_triangle = _calibrate_timer(
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
        self._timer_calibrate_diamond_triangle.cancel()
        app_model.inference.pose_response_ready -= record_offsets
        algo.pellet_delivery_enabled = before_pellet_delivery_enabled
        action.setIcon(qta.icon("fa5s.crosshairs"))
        action.setChecked(False)
        #
        self._diamond_triangle_calib_run = None  # MUST be before
        self._post_api_event(ApiEventKind.calibrationDcsEnded)
        #
        self._handle_diamond_triangle_calib_run(
            positions=positions,
            offsets=offsets,
            diamond_locs3d=diamond_locs3d,
        )


    def on_calibrate_diamond_triangle(self, is_toggled):
        if is_toggled and self._diamond_triangle_calib_run is None:
            self._diamond_triangle_calib_run = self._make_diamond_triangle_calib_run()
        calib_run = self._diamond_triangle_calib_run
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

    def on_3d_calibrate(self, is_toggled):
        self.run_action.setEnabled(not is_toggled)
        if is_toggled:
            self._app_model.status = AppModelStatus.CALIBRATION_3D
            error = "Processing unfinished"
            result_dir: Path = None
            def handle_3d_calib():
                nonlocal error, result_dir
                self._post_api_event(ApiEventKind.calibration3dStarted)
                try:
                    result_dir = make_3d_calib(self._app_model)
                except Exception as err:
                    logger.exception("3d-calib failed: %s", err)
                    error = err
                else:
                    error = None

            def show_result():
                self.run_action.setEnabled(True)
                self.make_3d_calib_action.setChecked(False)
                self.make_3d_calib_action.setEnabled(True)
                self._app_model.status = AppModelStatus.IDLE
                logger.verbose("3d-calib thread joined, error=%s", error)
                if error is None:
                    target = Path(self._preferences.configuration_location).joinpath(DEFAULT_3D_CALIB_DIR_NAME)
                    if target.exists():
                        rsp = QMessageBox.question(
                            self,
                            "3D calibration success",
                            f"Calibration dir already exists ({target}),\n\n"
                            f"do you want to replace ?",
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                        if rsp != QMessageBox.StandardButton.Yes:
                            return
                        now = datetime.now()
                        backup_path = target.parent.joinpath(f"{target.name}_{now.strftime(DATE_TIME_FORMAT)}")
                        target.rename(backup_path)
                        logger.debug("Previous 3d-calib moved to %s", backup_path)
                    shutil.copytree(
                        result_dir, target,
                        dirs_exist_ok=False,  # default already, but to be sure we want be clean
                    )
                    QMessageBox.information(
                        self,
                        "3D calibration success", f"Result saved into {target}", QMessageBox.StandardButton.Ok)
                else:
                    QMessageBox.warning(self, "3D calibration failed", f"Error received: {error}", QMessageBox.StandardButton.Ok)

            def wait_3d_calib_done(thread):
                executor_thread.join()
                self._post_api_event(ApiEventKind.calibration3dEnded)
                InvokeMethod(show_result)

            executor_thread = threading.Thread(target=handle_3d_calib, name="3d-calibration", daemon=True)
            executor_thread.start()

            waiter_thread = threading.Thread(target=wait_3d_calib_done, name="wait-3d-calibration",
                                             args=(executor_thread,), daemon=True)
            waiter_thread.start()

    def _make_show_msg_box(self, title, text, icon):
        def show():
            box = QMessageBox()
            box.setWindowTitle(title)
            # box.setModal(True)
            box.setText(text)
            box.setIcon(icon)
            box.show()
            self._add_box_to_open_dialogs(box)
        return show

    def _check_diamond_triangle_config(self):
        algo = self._app_model.behavior.algorithm
        dcs_cfg = algo.diamond_triangle_config
        if dcs_cfg is None or not dcs_cfg.fully_valid:
            title = "Missing, or invalid, Diamond-Triangle config"
            if self._app_model.inference.status == InferenceStatus.live:
                text = (
                    f"\n{algo.diamond_triangle_offset_config_path} is missing or not fully valid,\n\n"
                    "Now that application is running:\n\n"
                    "1) Using Hardware Control Set + Send buttons: move the triangle near the desired deliver position\n\n"
                    "2) Then, execute a calibration via menu Tools -> Calibrate Coordinate System\n\n")
                
            else:
                text = (
                    f"\n{algo.diamond_triangle_offset_config_path} is either missing or needs update,\n\n"
                    "Once application will be running:\n\n"
                    "1) Using Hardware Control Set + Send buttons: move the triangle near the desired deliver position\n\n"
                    "2) Execute a new coordinate calibration via menu Tools -> Calibrate Coordinate System\n\n")
            #
            InvokeMethod(self._make_show_msg_box(title, text, QMessageBox.Icon.Warning))

    def on_activated(self):
        self._check_diamond_triangle_config()
        self.main_content.on_activated()

    def _finish_close(self):
        logger.info("finishing close ..")
        self.main_content.close()
        dialogs = self._open_dialogs
        self._open_dialogs = []
        for dialog in dialogs:
            dialog.close()
        super().close()

    def close(self):
        logger.debug("received close")
        with self._app_model.app_lock:
            event = self._close_event
            if self._closing:
                if event is not None:
                    event.accept()
                    self._close_event = None
                else:
                    logger.warning("already closing")
                return
            if event is not None:
                event.ignore()
                self._close_event = None
            self._closing = True

        def execute_close():
            self.on_capture_start_stop(False)
            stop_thread = self._stop_capture_thread
            self._timer_calibrate_diamond_triangle.cancel()
            if stop_thread is not None:
                logger.debug("joining stop capture thread")
                stop_thread.join()
            self._app_model.on_close()
            InvokeMethod(self._finish_close)
        close_thread = threading.Thread(target=execute_close)
        close_thread.start()

    def closeEvent(self, event):
        logger.debug("received closeEvent: %s", event)
        self._close_event = event
        self.close()

    def moveEvent(self, e):
        self._preferences.last_window_x = self.pos().x()
        self._preferences.last_window_y = self.pos().y()
        super(MainWindow, self).moveEvent(e)

    def _edit_camera_settings(self):
        # isChecked() has already swapped to the new value by the time this is called
        if not self.edit_camera_settings_action.isChecked():
            self.main_content.set_is_editable(False)
            self.run_action.setEnabled(True)
        else:
            self.main_content.set_is_editable(True)
            self.run_action.setEnabled(False)

    def _show_preferences(self):
        dialog = PreferencesDialog(self._preferences, self._app_model)
        dialog.exec()

    def _create_actions(self):
        action = self.edit_camera_settings_action = QAction(QIcon(qta.icon("fa5s.edit")), "Edit Camera Settings", self)
        action.setToolTip("Edit Camera Settings")
        action.setCheckable(True)
        action.setChecked(False)
        action.triggered.connect(self._edit_camera_settings)

        action = self.run_action = QAction(QIcon(qta.icon("ei.play")), "Start", self)
        action.setToolTip("Start or stop acquisition")
        action.setCheckable(True)
        action.setShortcut(QKeySequence(Qt.CTRL | Qt.Key_R))
        action.triggered.connect(self.on_capture_start_stop)

        action = self.next_training_phase_action = QAction(QIcon(qta.icon("fa5s.arrow-alt-circle-right")), "Next Phase", self)
        action.setVisible(False)
        action.setShortcut(QKeySequence(Qt.CTRL | Qt.Key_R))
        action.triggered.connect(self.on_next_plan_phase)

        action = self.previous_training_phase_action = QAction(QIcon(qta.icon("fa5s.arrow-alt-circle-left")), "Previous Phase", self)
        action.setVisible(False)
        action.setShortcut(QKeySequence(Qt.CTRL | Qt.Key_R))
        action.triggered.connect(self.on_previous_plan_phase)

        self._diamond_triangle_calib_run = None
        self._timer_calibrate_diamond_triangle = no_op_timer
        action = self.calib_diamond_triangle_action = QAction(QIcon(qta.icon("fa5s.crosshairs")), "Calibrate Coordinate System", self)
        action.setToolTip("Calibrate the relative offset between the pellet delivery spoon and the tunnel")
        action.setCheckable(True)
        action.triggered.connect(self.on_calibrate_diamond_triangle)
        action.setEnabled(False)

        action = self.make_3d_calib_action = QAction(QIcon(qta.icon("fa5s.crosshairs")), "Make 3D calibration", self)
        action.setCheckable(True)
        action.triggered.connect(self.on_3d_calibrate)

        action = self.view_diagnostics_action = QAction("Diagnostics", self)
        action.setToolTip("Show or hide diagnostics panel")
        action.setCheckable(True)
        action.setChecked(self.main_content.is_diagnostics_visible)
        action.triggered.connect(lambda: self._toggle_diagnostics_view())

        action = self.load_cell_trigger_action = QAction("Load Cell", self)
        action.setCheckable(True)
        action.triggered.connect(self._internal_simulate_trigger_load_cell)

        action = self.force_headbar_detector_action = QAction("HeadBar", self)
        action.setCheckable(True)
        action.triggered.connect(self._internal_set_force_headbar_detector)

        action = self.pellet_seen_action = QAction("Pellet Seen", self)
        action.triggered.connect(self._internal_set_pellet_seen)

        action = self.mouse_seen_action = QAction("Mouse Seen", self)
        action.triggered.connect(self._internal_set_mouse_seen)

        action = self.mouse_near_pellet_action = QAction("Hands near pellet", self)
        action.triggered.connect(self._internal_mouse_near_pellet)

        action = self.analysis_results_action = QAction("Analysis-Result", self)
        action.setCheckable(True)
        action.triggered.connect(self._internal_detection_result_toggle)

        action = self.preferences_action = QAction(QIcon(qta.icon("fa5s.cog")), "Preferences", self)
        action.triggered.connect(lambda: self._show_preferences())

        action = self.emergency_stop_action = QAction("Emergency", self)
        action.setCheckable(True)

        action = self.quit_action = QAction("Quit")
        action.setShortcut(QKeySequence(Qt.CTRL | Qt.Key_Q))
        action.triggered.connect(lambda: self._app.quit())

    def _configure_menubar(self):
        menu_bar = self.menuBar()

        menu_bar.setObjectName("MenuBar")
        menu_bar.setStyleSheet("#MenuBar {background-color: #eee}")

        file_menu = menu_bar.addMenu("File")
        file_menu.addAction(self.quit_action)

        edit_menu = menu_bar.addMenu("Edit")
        edit_menu.addAction(self.edit_camera_settings_action)

        tools_menu = menu_bar.addMenu("Tools")
        tools_menu.addAction(self.calib_diamond_triangle_action)
        tools_menu.addAction(self.make_3d_calib_action)

        if self._is_dev:
            view_menu = menu_bar.addMenu("View")
            view_menu.addAction(self.view_diagnostics_action)

    def _configure_toolbar(self):

        app_model = self._app_model
        behavior = app_model.behavior

        toolbar = QToolBar("Run Toolbar")
        toolbar.setFloatable(False)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        toolbar.addAction(self.run_action)

        toolbar.addAction(self.previous_training_phase_action)
        toolbar.addAction(self.next_training_phase_action)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar.addWidget(spacer)

        toolbar.addWidget(QLabel("Notes:"))
        self._notes = QLineEdit()
        self._notes.setMinimumWidth(100)
        self._notes.setText(self._app_model.notes)
        self._notes.textChanged.connect(self.notes_changed)
        self._notes.setContentsMargins(4, 0, 8, 0)
        # note: this margin allows the emergency button to be greater
        toolbar.addWidget(self._notes)

        toolbar.addWidget(QLabel("Subject:"))
        combo = self._animal_dropdown = QComboBox()
        combo.setMinimumWidth(100)
        combo.setEditable(True)
        combo.setDuplicatesEnabled(False)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        combo.currentIndexChanged.connect(self._animal_changed)
        combo.lineEdit().editingFinished.connect(self._add_animal)
        toolbar.addWidget(combo)

        toolbar.addSeparator()

        label = QLabel("Training Mode:")
        label.setContentsMargins(8, 0, 0, 0)
        toolbar.addWidget(label)
        combo = self._training_mode_combo = QComboBox()
        toolbar.addWidget(combo)
        combo.setDuplicatesEnabled(False)
        for mode in TrainingMode:
            combo.addItem(mode.value,
                          (mode,)  # userData: encapsulated in a tuple,
                          # otherwise pyside drops the enum member and only keep the value string.
                          # this is because it's a typed str-subclass enum.
                          )

        def training_mode_index_changed(_):
            selected_mode = self._training_mode_combo.currentData()[0]  # unpack from tuple, see above.
            app_model.training_mode = selected_mode
        combo.currentIndexChanged.connect(training_mode_index_changed)

        label = QLabel("Protocol:")
        label.setContentsMargins(8, 0, 0, 0)
        widget = QWidget()
        self._widget_training_plan_action = toolbar.addWidget(widget)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label)
        combo = self._training_plan_combo = QComboBox()
        layout.addWidget(combo)

        def training_plan_index_changed(_):
            plan_id = self._training_plan_combo.currentData()
            selected_plan: Optional[TrainingPlan] = app_model.get_training_plan_by_id(plan_id)
            logger.debug("plan changed: %s -> %s", plan_id, selected_plan)
            app_model.training_plan = selected_plan

        combo.currentIndexChanged.connect(training_plan_index_changed)

        def update_training_mode(training_mode):
            logger.debug("Updating training_mode to %s", training_mode)
            self._widget_training_plan_action.setVisible(training_mode != TrainingMode.MANUAL)
            animal = app_model.selected_animal
            plan_id = None if animal is None else animal.training.current_protocol
            training_plan_idx = self._training_plan_index_by_plan_id.get(plan_id, -1)
            self._training_plan_combo.blockSignals(True)
            self._training_plan_combo.setCurrentIndex(training_plan_idx)
            self._training_plan_combo.blockSignals(False)
            # self.main_content.training_plan_changed.emit(self._app_model.training_plan)
            self._app_model.training_mode = training_mode
            self._refresh_prev_next_phases()

        update_training_mode(self._app_model.training_mode)
        self.training_mode_changed.connect(update_training_mode)

        toolbar.addSeparator()

        toolbar.addAction(self.preferences_action)

        toolbar.addSeparator()

        emergency_button = QPushButton("Emergency")
        emergency_button.setCheckable(True)
        emergency_button.setObjectName("EmergencyButton")
        emergency_button.setStyleSheet("#EmergencyButton {background-color: red; color: white; min-width: 100px}")

        def update_emergency_ui(is_toggled: bool, source: str):
            emergency_button.setText("Resume" if is_toggled else "Emergency")
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

        if self._is_dev:
            self.addToolBarBreak()
            toolbar = self._dev_toolbar = QToolBar("Dev Toolbar")
            toolbar.setContentsMargins(0, 0, 0, 0)
            # toolbar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
            self.addToolBar(toolbar)
            toolbar.setFloatable(False)
            toolbar.setMovable(False)
            toolbar.addAction(self.load_cell_trigger_action)
            toolbar.addAction(self.force_headbar_detector_action)
            toolbar.addAction(self.pellet_seen_action)
            toolbar.addAction(self.mouse_seen_action)
            toolbar.addAction(self.mouse_near_pellet_action)
            toolbar.addAction(self.analysis_results_action)
            widget = QWidget()
            widget.setContentsMargins(4, 0, 0, 0)
            self._internal_analysis_widget_toolbar = toolbar.addWidget(widget)
            self._internal_analysis_widget_toolbar.setVisible(False)
            hbox = QHBoxLayout(widget)
            label = QLabel("P:")
            label.setToolTip("Pellets Presented")
            hbox.addWidget(label)
            spinbox = self._internal_pellet_presented_spinbox = QSpinBox()
            spinbox.setToolTip(label.toolTip())
            hbox.addWidget(spinbox)
            label = QLabel("R:")
            label.setToolTip("Pellets Reached")
            hbox.addWidget(label)
            spinbox = self._internal_pellet_reached_spinbox = QSpinBox()
            spinbox.setToolTip(label.toolTip())
            hbox.addWidget(spinbox)
            label = QLabel("C:")
            label.setToolTip("Pellets Consumed")
            hbox.addWidget(label)
            spinbox = self._internal_pellet_consumed_spinbox = QSpinBox()
            spinbox.setToolTip(label.toolTip())
            hbox.addWidget(spinbox)
            hbox.addWidget(QLabel("Shift:"))
            spinbox = self._internal_shift_x_spinbox = QDoubleSpinBox()
            spinbox.setToolTip("X shift")
            spinbox.setRange(-9, 9)
            spinbox.setDecimals(1)
            hbox.addWidget(spinbox)
            spinbox = self._internal_shift_y_spinbox = QDoubleSpinBox()
            spinbox.setToolTip("Y shift")
            spinbox.setRange(-9, 9)
            spinbox.setDecimals(1)
            hbox.addWidget(spinbox)
            spinbox = self._internal_shift_z_spinbox = QDoubleSpinBox()
            spinbox.setToolTip("Z shift")
            spinbox.setRange(-9, 9)
            spinbox.setDecimals(1)
            hbox.addWidget(spinbox)
            # for i in range(hbox.count()):
            #     w = hbox.itemAt(i).widget()
            #     # w.setContentsMargins(0, 0, 0, 0)
            #     # w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            # unnecessary with:
            hbox.setContentsMargins(0, 0, 0, 0)
            # plus:
            toolbar.setMaximumHeight(toolbar.minimumSizeHint().height())

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
        def show_in_gui_thread(title=title, message=message):
            dlg = QMessageBox(self)
            dlg.setWindowTitle(title)
            dlg.setText(message)
            dlg.exec()
        InvokeMethod(show_in_gui_thread)

    def _preferences_property_changed(self, name, value, _):
        if name == "log_level":
            self._update_log_level(value)
        elif name == "remove_raw_data_when_inactive_session":
            self._app_model.behavior.algorithm.clean_raw_data_on_inactive_session = value

    def _simulate_intersession_segmentation(self, intersession_block):
        logger.verbose("Simulate feed-intersession-analysis: %s", intersession_block)
        inference = self._app_model.inference
        inference._data_monitor_proc.stop_recorded.wait()
        logger.debug("got stop recorded")
        inference._data_monitor_proc.stop_recorded.clear()
        intersession_block.frame_count = 42
        time.sleep(2.5)

    @staticmethod
    def _simulate_intersession_process(*args, fake_result, **kwargs):
        # NB: must be static method given it's executed in a sub-process, so must no get the whole main-window
        # instance tried to be serialized (would most likely fails/error) !
        logger.verbose("Simulate intersession process: %s", fake_result)
        time.sleep(1.5)
        return fake_result

    def _internal_simulate_trigger_load_cell(self):
        is_checked = self.load_cell_trigger_action.isChecked()
        app_model = self._app_model
        load_cell_monitor = app_model.analysis.load_cell_monitor
        if not is_checked and self.analysis_results_action.isChecked():
            logger.verbose("Patching intersession segmentation and detection with simulate")
            inference = app_model.inference
            inference._feed_intersession_analysis_execute = self._simulate_intersession_segmentation
            res = IntersessionResponse(
                pellets_presented=self._internal_pellet_presented_spinbox.value(),
                successful_reaches=self._internal_pellet_reached_spinbox.value(),
                food_consumed=self._internal_pellet_consumed_spinbox.value(),
                pellet_x=self._internal_shift_x_spinbox.value(),
                pellet_y=self._internal_shift_y_spinbox.value(),
                pellet_z=self._internal_shift_z_spinbox.value(),
            )
            inference._intersession_process_execute = partial(self._simulate_intersession_process, fake_result=res)
        load_cell_monitor.force_engaged(is_checked)

    def _internal_set_force_headbar_detector(self):
        new_value = self.force_headbar_detector_action.isChecked()
        self._app_model.analysis.headbar_pressure_monitor.force_engaged(new_value)

    def _internal_set_pellet_seen(self):
        self._app_model.behavior.algorithm.update_pellet_seen(True)

    def _internal_set_mouse_seen(self):
        self._app_model.behavior.algorithm.update_mouse_seen(True)

    def _internal_mouse_near_pellet(self):
        behavior = self._app_model.behavior
        algo = behavior.algorithm
        uncover_dist = algo.pellet_hand_uncover_distance
        if uncover_dist is not None:
            new_val = uncover_dist / 2
        else:
            new_val = 0.001  # that is on it
        logger.debug("set pellet_hands_min_distance to %s", new_val)
        algo.pellet_hands_min_distance = new_val

    def _internal_detection_result_toggle(self):
        inference = self._app_model.inference
        is_checked = self.analysis_results_action.isChecked()
        self._internal_analysis_widget_toolbar.setVisible(is_checked)
        if is_checked:
            self._orig_inference_analysis_feed = inference._feed_intersession_analysis_execute
            self._orig_inference_analysis_process = inference._intersession_process_execute
        else:
            logger.verbose("Restoring intersession segmentation and detection to real procedures")
            inference._feed_intersession_analysis_execute = self._orig_inference_analysis_feed
            inference._intersession_process_execute = self._orig_inference_analysis_process

    def notes_changed(self, value: str):
        self._app_model.notes = value

    def _add_animal(self):
        self._app_model.add_animal(self._animal_dropdown.currentText(), select=True)

    def _animal_changed(self, _):
        if self._animal_dropdown.currentIndex() in (0, -1):
            self._app_model.selected_animal = None
        else:
            animal_id = self._animal_dropdown.currentData()
            animal: AnimalSubject = self._app_model.get_animal_by_id(animal_id)
            self._app_model.selected_animal = animal

    def _refresh_prev_next_phases(self):
        attached = self._app_model.attached_plan
        if attached is None or self._app_model.training_mode != TrainingMode.MANUAL_WITH_PROTOCOL:
            self.previous_training_phase_action.setVisible(False)
            self.next_training_phase_action.setVisible(False)
            return
        for action, can_do, direction in (
            (self.previous_training_phase_action, attached.can_fallback, "left"),
            (self.next_training_phase_action, attached.can_advance, "right"),
        ):
            action.setVisible(True)
            name = f"fa5s.arrow-alt-circle-{direction}"
            action.setIcon(qta.icon(name))
            action.setEnabled(can_do)

    def _app_model_property_changed(self, name: str, value, _):
        props = self._app_model.Props
        #
        if name == props.ACQUISITION_RUNNING:
            self.running_status_changed.emit(value)

        elif name == props.ANIMALS:
            self._reload_animals(value)

        elif name == props.SELECTED_ANIMAL:
            animal_dropdown = self._animal_dropdown
            animal_dropdown.blockSignals(True)
            if value is None:
                animal_dropdown.setCurrentIndex(0)
            else:
                assert isinstance(value, AnimalSubject)
                index = animal_dropdown.findText(value.name)
                if index != -1:
                    animal_dropdown.setCurrentIndex(index)
                else:
                    logger.warning("Cannot select animal %s given not in current list")
                    animal_dropdown.addItem(value.name, value.id)

            animal_dropdown.blockSignals(False)
            self._refresh_prev_next_phases()

        elif name == props.TRAINING_MODE:
            self.training_mode_changed.emit(value)

        elif name == props.TRAINING_PLAN:
            if value is not None:
                assert isinstance(value, TrainingPlan)
                index = self._training_plan_index_by_plan_id.get(value.plan_id, -1)
            else:
                index = -1
            logger.debug("changing plan: index=%s -> %s", index, None if value is None else value.name)
            self._training_plan_combo.blockSignals(True)
            self._training_plan_combo.setCurrentIndex(index)
            self._training_plan_combo.blockSignals(False)
            self._refresh_prev_next_phases()

        elif name == props.TRAINING_PLANS:
            self._set_training_plans()

        elif name == props.TRAINING_PHASE:
            self._refresh_prev_next_phases()

    def _reload_animals(self, animals: List[AnimalSubject]):
        # get current selected animal before adding them,
        # given when adding that's modifying the currently selected one too,
        # which reset the preference selected to that one...
        find_animal_name = (
            self._preferences.selected_animal if self._app_model.selected_animal is None
            else self._app_model.selected_animal.name
        )

        # prevent on_animal_changed event:
        combo = self._animal_dropdown
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("", None)
        for idx, animal in enumerate(animals):
            combo.addItem(animal.name, animal.id)
        combo.blockSignals(False)

        # we set the good one here:
        if find_animal_name is not None:
            index = combo.findText(find_animal_name)
            if index != -1:
                combo.setCurrentIndex(index)
        else:
            combo.setCurrentIndex(0)

    @staticmethod
    def _update_log_level(value: int):
        # controlled via console and file handlers now
        get_console_handler().setLevel(value)

    def _inference_property_changed(self, name: str, value, old_value):
        inference = self._app_model.inference
        if name == inference.STATUS:
            self.calib_diamond_triangle_action.setEnabled(value == InferenceStatus.live)
            if value == InferenceStatus.live:
                self._check_diamond_triangle_config()

    def _behavior_algo_property_changed(self, name, value, _):
        pass

    def _set_training_plans(self):
        app_model = self._app_model
        combo = self._training_plan_combo
        combo.blockSignals(True)
        combo.clear()
        plans = app_model.training_plans
        has_some = len(plans) > 0
        empty_txt = "" if has_some else " " * 64
        tooltip_txt = (
            "Select a training protocol" if has_some
            else "There are no training protocols in the Autotrainer folder"
        )
        combo_indices_map: Dict[Optional[str], int]
        combo_indices_map = self._training_plan_index_by_plan_id = {
            get_plan_id(plan): idx
            for idx, plan in enumerate(plans)
        }
        for plan_index, plan in enumerate(plans):
            # plan = TrainingPlan.from_dict(plan, no_transition=True)
            combo.addItem(plan['name'], userData=get_plan_id(plan))
            combo.setItemData(plan_index, plan['description'], Qt.ToolTipRole)
        combo.addItem(empty_txt, userData=None)  # put it last
        combo_indices_map[None] = len(plans)
        combo.setItemData(len(plans), tooltip_txt, Qt.ToolTipRole)
        combo.blockSignals(False)
        animal = app_model.selected_animal
        if animal is None:
            combo.blockSignals(True)  # required to not induce loop
            combo.setCurrentIndex(len(plans))
            combo.blockSignals(False)  # required to not induce loop
            return
        plan_id = animal.training.current_protocol
        combo.blockSignals(True)  # required to not induce loop
        if plan_id is None:
            combo.setCurrentIndex(len(plans))
        else:
            plan_combo_index = self._training_plan_index_by_plan_id.get(plan_id, None)
            if plan_combo_index is None:
                logger.warning("Animal has current protocol %r but no such protocol found", plan_id)
                combo.setCurrentIndex(len(plans))
            else:
                combo.setCurrentIndex(plan_combo_index)
        combo.blockSignals(False)  # required to not induce loop

    def _on_app_model_configuration_loaded(self, config):
        self._set_training_plans()
