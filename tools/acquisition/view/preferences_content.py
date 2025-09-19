import logging

import verboselogs
from PySide6 import QtCore
from PySide6.QtWidgets import (QWidget, QFormLayout, QLineEdit, QComboBox, QLabel, QHBoxLayout, QPushButton,
                               QFileDialog, QTabWidget, QVBoxLayout, QCheckBox, QDoubleSpinBox, QSpinBox)

from autotrainer.core.logging import get_verbose_logger
from autotrainer.pyside import QSwitch

from tools.acquisition.model.app_model import AppModel
from tools.acquisition.model.user_preferences import UserPreferences
from tools.acquisition.view.analysis_content import AVAILABLE_GRAPHS

logger = get_verbose_logger(__name__)


class PreferencesContent(QWidget):
    def __init__(self, preferences: UserPreferences, app_model: AppModel):
        super(PreferencesContent, self).__init__(None)

        self._preferences = preferences
        self._app_model = app_model

        self._tabs = QTabWidget(self)

        self._general_tab = self._create_general_tab()
        self._tabs.addTab(self._general_tab, "General")

        self._behavior_tab = self._create_behavior_tab()
        self._tabs.addTab(self._behavior_tab, "Behavior")

        self._analysis_tab = self._create_analysis_tab()
        self._tabs.addTab(self._analysis_tab, "Analysis")

        self._advanced_tab = self._create_advanced_tab()
        self._tabs.addTab(self._advanced_tab, "Advanced")

        layout = QVBoxLayout()
        layout.addWidget(self._tabs)

        self.setLayout(layout)

    def _create_general_tab(self):
        self._device_id_edit = QLineEdit(None, None)
        self._device_id_edit.setText(self._preferences.serial_number)
        self._device_id_edit.textChanged.connect(self._device_id_changed)

        self._data_location_edit = QLineEdit(None, None)
        self._data_location_edit.setText(self._app_model.output_location)
        self._data_location_edit.textChanged.connect(self._data_location_changed)

        self._animal_location_edit = QLineEdit(None, None)
        self._animal_location_edit.setText(self._preferences.animal_location)
        self._animal_location_edit.textChanged.connect(self._animal_location_changed)

        form_layout = QFormLayout(None)

        form_layout.addRow("Device Id:", self._device_id_edit)

        layout = QHBoxLayout()
        layout.addWidget(self._data_location_edit)
        button = QPushButton("Select...")
        button.clicked.connect(lambda: self._browse_for_location("data"))
        layout.addWidget(button)

        form_layout.addRow("Data location:", layout)

        layout = QHBoxLayout()
        layout.addWidget(self._animal_location_edit)
        button = QPushButton("Select...")
        button.clicked.connect(lambda: self._browse_for_location("animal"))
        layout.addWidget(button)

        form_layout.addRow("Animal location:", layout)

        tab = QWidget(None)
        tab.setLayout(form_layout)

        return tab

    def _create_behavior_tab(self):
        app_model = self._app_model
        behavior = app_model.behavior
        analysis = behavior.analysis
        algo = behavior.algorithm
        form_layout = QFormLayout(None)

        layout = QHBoxLayout()
        toggle = self._inference_enabled_toggle = QSwitch()
        def inference_enabled_state_changed(x: int):
            new_enabled = x != 0
            app_model.inference.is_enabled = new_enabled
            self._pellet_delivery_toggle.setEnabled(new_enabled)
            self._pellet_delivery_toggle.setEnabled(new_enabled)
            self._pellet_cover_toggle.setEnabled(new_enabled and algo.pellet_delivery_enabled)
            # self._intersession_toggle.setEnabled(new_enabled)
            self._allow_intersession_shift_toggle.setEnabled(new_enabled and behavior.is_intersession_enabled)
        toggle.setToolTip("Enables real-time pose inference during live sessions (mouse in tunnel).")
        toggle.setChecked(app_model.inference.is_enabled)
        toggle.stateChanged.connect(inference_enabled_state_changed)  # after setChecked
        layout.addWidget(toggle)
        layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        form_layout.addRow("Live Analysis:", layout)
        #
        layout = QHBoxLayout()
        self._inference_model_edit = QLineEdit(None, None)
        self._inference_model_edit.setText(self._app_model.inference.model_location)
        self._inference_model_edit.textChanged.connect(self._inference_model_changed)
        layout.addWidget(self._inference_model_edit)
        button = QPushButton("Select...")
        button.clicked.connect(lambda: self._browse_for_location("inference_model"))
        layout.addWidget(button)
        layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        form_layout.addRow("Inference model:", layout)
        #
        layout = QHBoxLayout()
        toggle = self._pellet_delivery_toggle = QSwitch()
        def pellet_delivery_state_changed(x: int):
            algo.pellet_delivery_enabled = x != 0
        toggle.stateChanged.connect(pellet_delivery_state_changed)
        toggle.setToolTip(
            "Enables pellet load-send-release cycles based on pellet detection and related factors.")
        toggle.setChecked(algo.pellet_delivery_enabled)
        layout.addWidget(toggle)
        layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        form_layout.addRow("Deliver Pellets:", layout)
        #
        layout = QHBoxLayout()
        toggle = self._pellet_cover_toggle = QSwitch()
        def pellet_cover_toggle_state_changed(x: int):
            algo.pellet_cover_enabled = x != 0
        toggle.stateChanged.connect(pellet_cover_toggle_state_changed)
        toggle.setChecked(algo.pellet_cover_enabled)
        toggle.setToolTip(
            "Covers the pellet when the mouse is not in the tunnel.  Release then generates a tone when the tunnel is "
            "entered.")
        layout.addWidget(toggle)
        layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        form_layout.addRow("Cover Pellets:", layout)
        #
        layout = QHBoxLayout()
        spinbox = self._auto_clamp_threshold_spinbox = QSpinBox(None)
        spinbox.setValue(analysis.headbar_pressure_monitor.load_cell_engaged_threshold)
        spinbox.setMinimum(0)
        spinbox.setMaximum(1023)
        spinbox.setWrapping(False)
        def update_headbar_pressure_threshold(value):
            analysis.headbar_pressure_monitor.load_cell_engaged_threshold = value
        spinbox.valueChanged.connect(update_headbar_pressure_threshold)
        spinbox.setEnabled(algo.head_fixation_enabled)
        spinbox.setToolTip("A value that adjusts the sensitivity of the headbar detector for it to be considered engaged.")
        layout.addWidget(spinbox)
        layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        form_layout.addRow("Auto-Clamp Threshold:", layout)
        #
        layout = QHBoxLayout()
        toggle = self._allow_intersession_shift_toggle = QSwitch()
        toggle.setToolTip("Enables adjustment of the pellet delivery position based on post-session reach analysis.")
        toggle.setEnabled(app_model.inference.is_enabled)
        toggle.setChecked(algo.intersession_pellet_shift_enabled)
        def allow_intersession_shift_toggle_state_changed(x: int):
            enabled = x != 0
            if enabled:
                behavior.is_intersession_enabled = True
            algo.intersession_pellet_shift_enabled = enabled
        toggle.stateChanged.connect(allow_intersession_shift_toggle_state_changed)
        layout.addWidget(toggle)
        layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        form_layout.addRow("Intersession Pellet Shift:", layout)
        #
        layout = QHBoxLayout()
        toggle = self._auto_correct_motors_drift_toggle = QSwitch()
        toggle.setChecked(self._app_model.behavior.algorithm.auto_correct_motors_drift)

        def auto_correct_motors_drift_toggle_changed(value: int):
            enabled = value != 0
            logger.verbose("auto_correct_motors_drift_toggle_changed: %s", enabled)
            self._app_model.behavior.algorithm.auto_correct_motors_drift = enabled

        toggle.stateChanged.connect(auto_correct_motors_drift_toggle_changed)
        layout.addWidget(toggle)
        layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        form_layout.addRow("Auto-correct motors drift:", layout)
        #
        self._use_triangle_pellet_distance = algo.use_triangle_pellet_distance_too_far
        layout = QHBoxLayout()
        toggle = self._toggle_use_triangle_pellet_distance = QSwitch()

        def use_triangle_pellet_distance_changed(value):
            enabled = value != 0
            prev, self._use_triangle_pellet_distance = self._use_triangle_pellet_distance, enabled
            algo.use_triangle_pellet_distance_too_far = enabled

        toggle.stateChanged.connect(use_triangle_pellet_distance_changed)
        toggle.setChecked(algo.use_triangle_pellet_distance_too_far)
        layout.addWidget(toggle)
        layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        form_layout.addRow("Use triangle-pellet distance for pellet too far detection:", layout)
        #
        spin_box = self._triangle_pellet_expected_distance_spinbox = QDoubleSpinBox()
        spin_box.setRange(0, 100)
        spin_box.setValue(algo.triangle_pellet_expected_distance)

        def triangle_pellet_expected_distance_changed(value):
            algo.triangle_pellet_expected_distance = value

        spin_box.valueChanged.connect(triangle_pellet_expected_distance_changed)

        form_layout.addRow("Triangle-Pellet expected distance:", spin_box)

        spin_box = self._triangle_pellet_diff_too_far_threshold_spinbox = QDoubleSpinBox()
        spin_box.setRange(0, 20)
        spin_box.setValue(algo.triangle_pellet_diff_too_far_threshold)

        def triangle_pellet_diff_too_far_threshold_changed(value):
            algo.triangle_pellet_diff_too_far_threshold = value

        spin_box.valueChanged.connect(triangle_pellet_diff_too_far_threshold_changed)

        form_layout.addRow("Triangle-Pellet diff too far threshold:", spin_box)

        tab = QWidget(None)
        tab.setLayout(form_layout)

        return tab

    def _on_graph_combox_changed(self, idx: int):
        graph = self._measurement_graph_combo.itemData(idx)
        if graph is not None:
            self._preferences.measurement_graph = graph.name
        else:
            logger.warning("graph None")

    def _create_analysis_tab(self):
        form_layout = QFormLayout(None)
        combo = self._measurement_graph_combo = QComboBox()

        pref_graph_name = self._preferences.measurement_graph
        for idx, graph in enumerate(AVAILABLE_GRAPHS):
            combo.addItem(graph.display, graph)
            if graph.name == pref_graph_name:
                combo.setCurrentIndex(idx)

        combo.currentIndexChanged.connect(self._on_graph_combox_changed)

        form_layout.addRow("Measurement graph:", combo)

        tab = QWidget(None)
        tab.setLayout(form_layout)

        return tab

    def _create_advanced_tab(self):
        combo_log_level = self._log_level_combobox = QComboBox(None)
        for display, lvl in (
                ("Success", verboselogs.SUCCESS),  # 0
                ("Warning", logging.WARNING),  # 1
                ("Notice", verboselogs.NOTICE),  # 2
                ("Info", logging.INFO),  # 3
                ("Verbose", verboselogs.VERBOSE),  # 4
                ("Debug", logging.DEBUG),  # 5
                ("Spam", verboselogs.SPAM),  # 6
        ):
            combo_log_level.addItem(display, lvl)
        combo_log_level.currentIndexChanged.connect(self._log_level_changed)

        levels_to_idx = {
            verboselogs.SUCCESS: 0,
            logging.WARNING: 1,
            verboselogs.NOTICE: 2,
            logging.INFO: 3,
            verboselogs.VERBOSE: 4,
            logging.DEBUG: 5,
            verboselogs.SPAM: 6,
        }

        log_level_idx = levels_to_idx.get(self._preferences.log_level)  # default to preferences.log_level
        if log_level_idx is None:
            log_level_idx = min(levels_to_idx.items(), key=lambda i: abs(self._preferences.log_level - i[0]))[1]
        combo_log_level.blockSignals(True)
        combo_log_level.setCurrentIndex(log_level_idx)
        combo_log_level.blockSignals(False)

        self._log_location_edit = QLineEdit(None, None)
        self._log_location_edit.setText(self._preferences.log_location)
        self._log_location_edit.textChanged.connect(self._log_location_changed)

        form_layout = QFormLayout(None)

        layout = QHBoxLayout()
        layout.addWidget(self._log_location_edit)
        button = QPushButton("Select...")
        button.clicked.connect(lambda: self._browse_for_location("log"))
        layout.addWidget(button)

        form_layout.addRow("Log location:", layout)

        form_layout.addRow("", QLabel("Log location change requires restart.  Leave blank for default location."))
        form_layout.addRow("Log level:", self._log_level_combobox)

        # May want these back with some future additions.
        # form_layout.addRow(QWidget())
        # form_layout.addRow(ATSeparator())
        # form_layout.addRow(QWidget())

        self._checkbox_remove_raw_data_inactive_session = QCheckBox()
        self._checkbox_remove_raw_data_inactive_session.setChecked(
            self._preferences.remove_raw_data_when_inactive_session)
        self._checkbox_remove_raw_data_inactive_session.stateChanged.connect(
            self._remove_raw_data_when_inactive_session_changed)
        form_layout.addRow("Remove saved videos when animal not seen:", self._checkbox_remove_raw_data_inactive_session)

        tab = QWidget(None)
        tab.setLayout(form_layout)

        return tab

    def _device_id_changed(self, value: str):
        self._preferences.serial_number = value

    def _data_location_changed(self, value: str):
        self._app_model.output_location = value

    def _animal_location_changed(self, value: str):
        self._preferences.animal_location = value

    def _inference_model_changed(self, value: str):
        self._app_model.inference.model_location = value

    def _log_level_changed(self, value):
        # logging.root.debug("_log_level_changed: %s", value)
        # print("%s" % (repr_all_loggers(),))
        if value != -1:
            new_level = self._log_level_combobox.itemData(value)
            self._preferences.log_level = new_level
            # get_console_handler().setLevel(new_level)

    def _log_location_changed(self, value: str):
        self._preferences.log_location = value

    def _remove_raw_data_when_inactive_session_changed(self, value: bool):
        self._preferences.remove_raw_data_when_inactive_session = value

    def _browse_for_location(self, which: str):
        if which == "animal":
            initial_location = self._preferences.animal_location
        else:
            initial_location = self._preferences.log_location

        dirname = QFileDialog.getExistingDirectory(self, "Select Directory", initial_location)

        if len(dirname) > 0:
            if which == "animal":
                self._animal_location_edit.setText(dirname)
            elif which == "data":
                self._data_location_edit.setText(dirname)
            elif which == "inference_model":
                self._inference_model_edit.setText(dirname)
            else:
                self._log_location_edit.setText(dirname)
