import ast
import logging
import math

import verboselogs
from PySide6 import QtCore
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QFormLayout, QLineEdit, QComboBox, QLabel, QHBoxLayout, QPushButton,
                               QFileDialog, QTabWidget, QVBoxLayout, QCheckBox, QDoubleSpinBox, QSpinBox, QGridLayout,
                               QLayout, QSizePolicy, QMessageBox)

from autotrainer.core.configuration.behavior_configuration import HeadClampConfiguration, PelletDeliveryConfiguration
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

        self._alarms_tab = self._create_alarms_tab()
        self._tabs.addTab(self._alarms_tab, "Alarms")

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

        main_layout = QVBoxLayout()
        main_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        top_layout = QVBoxLayout()
        top_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        analysis_layout = QHBoxLayout()
        analysis_layout.addWidget(QLabel("Live Analysis:"))
        toggle = self._inference_enabled_toggle = QSwitch()
        edit = self._inference_model_edit = QLineEdit(None, None)
        button = self._button_select_model = QPushButton("Select...")
        def inference_enabled_state_changed(x: int):
            enabled = x != 0
            app_model.inference.is_enabled = enabled
            self._pellet_delivery_toggle.setEnabled(enabled)
            self._pellet_cover_toggle.setEnabled(enabled and algo.pellet_delivery_enabled)
            # self._intersession_toggle.setEnabled(new_enabled)
            self._allow_intersession_shift_toggle.setEnabled(enabled and behavior.is_intersession_enabled)
            self._inference_model_edit.setEnabled(enabled)
            self._button_select_model.setEnabled(enabled)
        toggle.setToolTip("Enables real-time pose inference during live sessions (mouse in tunnel).")
        toggle.setChecked(app_model.inference.is_enabled)
        toggle.stateChanged.connect(inference_enabled_state_changed)  # after setChecked
        analysis_layout.addWidget(toggle)
        analysis_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        top_layout.addLayout(analysis_layout)
        #
        inference_model_layout = QHBoxLayout()
        inference_model_layout.addWidget(QLabel("Inference model:"))
        edit.setText(self._app_model.inference.model_location)
        edit.textChanged.connect(self._inference_model_changed)
        inference_model_layout.addWidget(self._inference_model_edit)

        button.clicked.connect(lambda: self._browse_for_location("inference_model"))
        inference_model_layout.addWidget(button)
        inference_model_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        #
        top_layout.addLayout(inference_model_layout)
        main_layout.addLayout(top_layout)
        #
        cur_row = 0
        grid_layout = QGridLayout()
        grid_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        grid_layout.setSpacing(4)
        grid_layout.setHorizontalSpacing(10)
        main_layout.addLayout(grid_layout)

        toggle = self._pellet_delivery_toggle = QSwitch()
        def pellet_delivery_state_changed(x: int):
            algo.pellet_delivery_enabled = x != 0
        toggle.stateChanged.connect(pellet_delivery_state_changed)
        toggle.setToolTip(
            "Enables pellet load-send-release cycles based on pellet detection and related factors.")
        toggle.setChecked(algo.pellet_delivery_enabled)
        grid_layout.addWidget(QLabel("Deliver Pellets:"), cur_row, 0)
        grid_layout.addWidget(toggle, cur_row, 1)
        cur_row += 1
        #
        toggle = self._pellet_cover_toggle = QSwitch()
        def pellet_cover_toggle_state_changed(x: int):
            algo.pellet_cover_enabled = x != 0
        toggle.stateChanged.connect(pellet_cover_toggle_state_changed)
        toggle.setChecked(algo.pellet_cover_enabled)
        toggle.setToolTip(
            "Covers the pellet when the mouse is not in the tunnel.  Release then generates a tone when the tunnel is "
            "entered.")
        grid_layout.addWidget(QLabel("Cover Pellets:"), cur_row, 0)
        grid_layout.addWidget(toggle, cur_row, 1)
        cur_row += 1
        #
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
        grid_layout.addWidget(QLabel("Intersession Pellet Shift:"), cur_row, 0)
        grid_layout.addWidget(toggle, cur_row, 1)
        cur_row += 1
        #
        toggle = self._auto_correct_motors_drift_toggle = QSwitch()
        toggle.setChecked(self._app_model.behavior.algorithm.auto_correct_motors_drift)
        def auto_correct_motors_drift_toggle_changed(value: int):
            enabled = value != 0
            logger.verbose("auto_correct_motors_drift_toggle_changed: %s", enabled)
            self._app_model.behavior.algorithm.auto_correct_motors_drift = enabled

        toggle.stateChanged.connect(auto_correct_motors_drift_toggle_changed)
        grid_layout.addWidget(QLabel("Auto-correct motors drift:"), cur_row, 0)
        grid_layout.addWidget(toggle, cur_row, 1)
        cur_row += 1

        #
        self._use_triangle_pellet_distance = algo.use_triangle_pellet_distance_too_far
        toggle = self._toggle_use_triangle_pellet_distance = QSwitch()
        def use_triangle_pellet_distance_changed(value):
            enabled = value != 0
            prev, self._use_triangle_pellet_distance = self._use_triangle_pellet_distance, enabled
            algo.use_triangle_pellet_distance_too_far = enabled
        toggle.stateChanged.connect(use_triangle_pellet_distance_changed)
        toggle.setChecked(algo.use_triangle_pellet_distance_too_far)
        grid_layout.addWidget(QLabel("Use triangle-pellet distance for pellet too far detection:"), cur_row, 0)
        grid_layout.addWidget(toggle, cur_row, 1)
        cur_row += 1
        #
        spin_box = self._triangle_pellet_expected_distance_spinbox = QDoubleSpinBox()
        spin_box.setRange(0, 100)
        spin_box.setValue(algo.triangle_pellet_expected_distance)
        def triangle_pellet_expected_distance_changed(value):
            algo.triangle_pellet_expected_distance = value
        spin_box.valueChanged.connect(triangle_pellet_expected_distance_changed)
        grid_layout.addWidget(QLabel("Triangle-Pellet expected distance:"), cur_row, 0)
        grid_layout.addWidget(spin_box, cur_row, 1)
        cur_row += 1
        #
        spin_box = self._triangle_pellet_diff_too_far_threshold_spinbox = QDoubleSpinBox()
        spin_box.setRange(0, 20)
        spin_box.setValue(algo.triangle_pellet_diff_too_far_threshold)
        def triangle_pellet_diff_too_far_threshold_changed(value):
            algo.triangle_pellet_diff_too_far_threshold = value
        spin_box.valueChanged.connect(triangle_pellet_diff_too_far_threshold_changed)
        grid_layout.addWidget(QLabel("Triangle-Pellet diff too far threshold:"), cur_row, 0)
        grid_layout.addWidget(spin_box, cur_row, 1)
        #
        cur_row = 0
        # pelletDelivery:maxPelletMissingSeconds
        spin_box = self._max_pellet_missing_seconds = QDoubleSpinBox()
        def max_pellet_missing_seconds_changed(value):
            algo.pellet_missing_time = value
        spin_box.setValue(algo.pellet_missing_time)
        spin_box.valueChanged.connect(max_pellet_missing_seconds_changed)
        grid_layout.addWidget(QLabel("Pellet missing seconds:"), cur_row, 2)
        grid_layout.addWidget(spin_box, cur_row, 3)
        cur_row += 1

        # pelletDelivery:pelletHandUncoverDistance [1]
        toggle = self._toggle_pellet_hand_uncover_distance = QSwitch()
        grid_layout.addWidget(QLabel("Pellet-hand minimum distance:"), cur_row, 2)
        toggle.setChecked(algo.pellet_hand_uncover_distance is not None)
        spin_box_pellet_hand_uncover_dist = self._pellet_hand_uncover_distance = QDoubleSpinBox()
        pellet_hand_uncover_label = QLabel("Pellet hand uncover distance (mm) :")
        def toggle_pellet_hand_uncover_distance_changed(value: int):
            enabled = value != 0
            if enabled:
                value = algo.pellet_hand_uncover_distance = PelletDeliveryConfiguration.pellet_hand_uncover_distance or 10
                spin_box_pellet_hand_uncover_dist.setValue(value)
            else:
                algo.pellet_hand_uncover_distance = None
            spin_box_pellet_hand_uncover_dist.setEnabled(enabled)
            spin_box_pellet_hand_uncover_dist.setVisible(enabled)
            pellet_hand_uncover_label.setVisible(enabled)
            # grid_layout.update()

        toggle.stateChanged.connect(toggle_pellet_hand_uncover_distance_changed)
        grid_layout.addWidget(toggle, cur_row, 3)
        cur_row += 1

        def pellet_hand_uncover_distance_changed(value):
            algo.pellet_hand_uncover_distance = value
        if algo.pellet_hand_uncover_distance is not None:
            spin_box_pellet_hand_uncover_dist.setValue(algo.pellet_hand_uncover_distance)
        spin_box_pellet_hand_uncover_dist.setMinimum(0)
        spin_box_pellet_hand_uncover_dist.setMaximum(100)
        spin_box_pellet_hand_uncover_dist.valueChanged.connect(pellet_hand_uncover_distance_changed)
        grid_layout.addWidget(pellet_hand_uncover_label, cur_row, 2)
        grid_layout.addWidget(spin_box_pellet_hand_uncover_dist, cur_row, 3)

        if algo.pellet_hand_uncover_distance is None:
            # ensure we hide the spinbox item/line
            toggle_pellet_hand_uncover_distance_changed(0)
        cur_row += 1

        # headClamp: autoClampReleaseToneFreq
        label = QLabel("Auto-Clamp:")
        label.setStyleSheet("font-weight: bold")
        grid_layout.addWidget(label, cur_row, 2)
        cur_row += 1

        #
        spin_box = self._auto_clamp_threshold_spinbox = QSpinBox(None)
        spin_box.setValue(analysis.headbar_pressure_monitor.load_cell_engaged_threshold)
        spin_box.setMinimum(0)
        spin_box.setMaximum(1023)
        spin_box.setWrapping(False)
        def update_headbar_pressure_threshold(value):
            analysis.headbar_pressure_monitor.load_cell_engaged_threshold = value
        spin_box.valueChanged.connect(update_headbar_pressure_threshold)
        spin_box.setEnabled(algo.head_fixation_enabled)
        spin_box.setToolTip("A value that adjusts the sensitivity of the headbar detector for it to be considered engaged.")
        grid_layout.addWidget(QLabel("Threshold:"), cur_row, 2)
        grid_layout.addWidget(spin_box, cur_row, 3)
        cur_row += 1

        spin_box = self._auto_clamp_release_tone_freq = QSpinBox()
        def auto_clamp_release_tone_freq_changed(value):
            algo.auto_clamp_release_tone_freq = value
        spin_box.setMinimum(0)
        spin_box.setMaximum(100_000)
        spin_box.setValue(algo.auto_clamp_release_tone_freq)
        spin_box.valueChanged.connect(auto_clamp_release_tone_freq_changed)
        grid_layout.addWidget(QLabel("Release tone freq (Hz) :"), cur_row, 2)
        grid_layout.addWidget(spin_box, cur_row, 3)
        cur_row += 1

        # headClamp:autoClampReleaseToneDelay
        spin_box = self._auto_clamp_release_tone_delay = QDoubleSpinBox()
        def auto_clamp_release_tone_delay_changed(value):
            algo.auto_clamp_release_tone_delay = value
        spin_box.setValue(algo.auto_clamp_release_tone_delay)
        spin_box.valueChanged.connect(auto_clamp_release_tone_delay_changed)
        grid_layout.addWidget(QLabel("Release tone delay (second) :"), cur_row, 2)
        grid_layout.addWidget(spin_box, cur_row, 3)
        cur_row += 1

        # headClamp:autoClampNoActivityReleaseDelay
        spin_box = self._auto_clamp_no_activity_release_delay = QDoubleSpinBox()
        def auto_clamp_no_activity_release_delay_changed(value):
            algo.auto_clamp_no_activity_release_delay = value
        spin_box.setValue(algo.auto_clamp_no_activity_release_delay)
        spin_box.valueChanged.connect(auto_clamp_no_activity_release_delay_changed)
        grid_layout.addWidget(QLabel("No-activity release delay (second) :"), cur_row, 2)
        grid_layout.addWidget(spin_box, cur_row, 3)
        cur_row += 1

        # headClamp:autoClampReleaseLoadCount
        spin_box = self._auto_clamp_release_load_count = QSpinBox()
        spin_box.setMinimum(0)
        spin_box.setMaximum(1_000_000)
        def auto_clamp_release_load_count_changed(value):
            algo.auto_clamp_release_load_count = value
        spin_box.setValue(algo.auto_clamp_release_load_count)
        spin_box.valueChanged.connect(auto_clamp_release_load_count_changed)
        grid_layout.addWidget(QLabel("Release load count:"), cur_row, 2)
        grid_layout.addWidget(spin_box, cur_row, 3)
        cur_row += 1

        #
        tab = QWidget(None)
        tab.setLayout(main_layout)

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
        model = self._app_model
        combo_log_level = self._log_level_combobox = QComboBox(None)
        combo_log_level.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
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
        combo_log_level.setCurrentIndex(log_level_idx)
        combo_log_level.currentIndexChanged.connect(self._log_level_changed)

        self._log_location_edit = QLineEdit(None, None)
        self._log_location_edit.setText(self._preferences.log_location)
        self._log_location_edit.textChanged.connect(self._log_location_changed)

        form_layout = QFormLayout(None)
        form_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

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

        form_layout.addRow("<b>TopCam Presence:</b>", QWidget())

        spinbox = self._presence_sum_percent_threshold_spinbox = QDoubleSpinBox()
        spinbox.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        spinbox.setRange(0, 100)
        spinbox.setSingleStep(0.1)
        spinbox.setDecimals(1)
        spinbox.setValue(model.top_camera_presence_detection.pc_threshold)
        def value_changed(value: float):
            model.top_camera_presence_detection.pc_threshold = value
        spinbox.valueChanged.connect(value_changed)
        form_layout.addRow("% threshold:", spinbox)

        spinbox = QDoubleSpinBox()
        spinbox.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        spinbox.setRange(0, 100)
        spinbox.setSingleStep(0.1)
        spinbox.setDecimals(1)
        spinbox.setValue(model.top_camera_presence_detection.pc_high_exclude_threshold)
        def value_changed(value: float):
            model.top_camera_presence_detection.pc_high_exclude_threshold = value
        spinbox.valueChanged.connect(value_changed)
        form_layout.addRow("high-% exclude threshold:", spinbox)

        spinbox = QSpinBox()
        spinbox.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        spinbox.setRange(0, 255)
        spinbox.setSingleStep(1)
        spinbox.setValue(model.top_camera_presence_detection.mask_lower_zero)
        def value_changed(value: float):
            model.top_camera_presence_detection.mask_lower_zero = value
        spinbox.valueChanged.connect(value_changed)
        form_layout.addRow("Mask Lower Zero:", spinbox)

        spinbox = QDoubleSpinBox()
        spinbox.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        spinbox.setRange(0, 100)
        spinbox.setSingleStep(0.1)
        spinbox.setDecimals(1)
        spinbox.setValue(model.top_camera_presence_detection.max_delay_skip_threshold)
        def value_changed(value: float):
            model.top_camera_presence_detection.max_delay_skip_threshold = value
        spinbox.valueChanged.connect(value_changed)
        form_layout.addRow("Max Delay Skip Seconds:", spinbox)

        tab = QWidget(None)
        tab.setLayout(form_layout)

        return tab

    def _create_alarms_tab(self):
        model = self._app_model
        analysis = model.analysis
        load_cell_monitor = analysis.load_cell_monitor
        config = model.loaded_configuration
        behavior_cfg = config.behavior

        main_layout = QVBoxLayout()
        main_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        # top_layout = QVBoxLayout()
        # top_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        # sub_layout = QHBoxLayout()
        # sub_layout.addWidget(QLabel("                                           "))
        # sub_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        # top_layout.addLayout(sub_layout)
        # main_layout.addLayout(top_layout)

        # not sure why but inner spinboxes are taking their max size while in behavior tab they don't
        # but we use similar layout scheme.
        # Found: behavior tab uses our QSwitch() which has a size hint
        grid_layout = QGridLayout()
        grid_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        grid_layout.setSpacing(4)
        grid_layout.setHorizontalSpacing(10)
        main_layout.addLayout(grid_layout)

        cur_row = 0
        alarm_cfg = analysis.emergency_alarm_monitor.config

        grid_layout.addWidget(QLabel("<b>Emergency Alarm Monitor</b>"), cur_row, 0)
        cur_row += 1

        grid_layout.addWidget(QLabel("<b>Use Audio & LoadCell thrashing:</b>"), cur_row, 0)
        toggle_use_audio_load_cell = QSwitch()
        toggle_use_audio_load_cell.setCheckable(True)
        toggle_use_audio_load_cell.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        def toggle_changed(value):
            toggled = value != 0
            alarm_cfg.use_audio_load_cell_thrash = toggled
        toggle_use_audio_load_cell.stateChanged.connect(toggle_changed)
        grid_layout.addWidget(toggle_use_audio_load_cell, cur_row, 1)
        cur_row += 1

        grid_layout.addWidget(QLabel("Auto-resume on Audio & LoadCell thrash stop:"), cur_row, 0)
        toggle_auto_resume_audio_load_cell = QSwitch()
        toggle_auto_resume_audio_load_cell.setCheckable(True)
        toggle_auto_resume_audio_load_cell.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        def toggle_changed(value):
            toggled = value != 0
            alarm_cfg.auto_resume_on_audio_load_cell_thrash_resume = toggled
        toggle_auto_resume_audio_load_cell.stateChanged.connect(toggle_changed)
        grid_layout.addWidget(toggle_auto_resume_audio_load_cell, cur_row, 1)
        cur_row += 1

        grid_layout.addWidget(QLabel("Thrash aggregate delay (seconds):"), cur_row, 0)
        spinbox = QDoubleSpinBox()
        spinbox.setRange(0, 60)
        spinbox.setDecimals(1)
        spinbox.setValue(alarm_cfg.audio_load_cell_thrash_aggregate_delay)
        spinbox.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        def value_changed(value):
            alarm_cfg.audio_load_cell_thrash_aggregate_delay = value
        spinbox.valueChanged.connect(value_changed)
        grid_layout.addWidget(spinbox, cur_row, 1)
        cur_row += 1

        grid_layout.addWidget(QLabel("LoadCell thrash % time:"), cur_row, 0)
        spinbox = QSpinBox()
        spinbox.setRange(0, 100)
        spinbox.setValue(alarm_cfg.load_cell_thrash_percent_on)
        spinbox.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        def value_changed(value):
            alarm_cfg.load_cell_thrash_percent_on = value
        spinbox.valueChanged.connect(value_changed)
        grid_layout.addWidget(spinbox, cur_row, 1)
        cur_row += 1

        grid_layout.addWidget(QLabel("LoadCell thrash count:"), cur_row, 0)
        spinbox = QSpinBox()
        spinbox.setRange(0, 100)
        spinbox.setValue(alarm_cfg.load_cell_thrash_count)
        spinbox.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        def value_changed(value):
            alarm_cfg.load_cell_thrash_count = value
        spinbox.valueChanged.connect(value_changed)
        grid_layout.addWidget(spinbox, cur_row, 1)
        cur_row += 1

        grid_layout.addWidget(QLabel("Audio thrash % time:"), cur_row, 0)
        spinbox = QSpinBox()
        spinbox.setRange(0, 100)
        spinbox.setValue(alarm_cfg.audio_thrash_percent_on)
        spinbox.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        def value_changed(value):
            alarm_cfg.audio_thrash_percent_on = value
        spinbox.valueChanged.connect(value_changed)
        grid_layout.addWidget(spinbox, cur_row, 1)
        cur_row += 1

        grid_layout.addWidget(QLabel("Audio thrash count:"), cur_row, 0)
        spinbox = QSpinBox()
        spinbox.setRange(0, 100)
        spinbox.setValue(alarm_cfg.audio_thrash_count)
        spinbox.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        def value_changed(value):
            alarm_cfg.audio_thrash_count = value
        spinbox.valueChanged.connect(value_changed)
        grid_layout.addWidget(spinbox, cur_row, 1)
        cur_row += 1

        #

        grid_layout.addWidget(QLabel("<b>Use presence missing after exit tunnel:</b>"), cur_row, 0)
        toggle = QSwitch()
        toggle.setCheckable(True)
        toggle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        def toggle_changed(value):
            toggled = value != 0
            alarm_cfg.use_presence_missing_after_exit_tunnel = toggled
        toggle.stateChanged.connect(toggle_changed)
        grid_layout.addWidget(toggle, cur_row, 1)
        cur_row += 1

        grid_layout.addWidget(QLabel("Auto-resume on presence seen after exit tunnel:"), cur_row, 0)
        toggle = QSwitch()
        toggle.setCheckable(True)
        toggle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        def toggle_changed(value):
            toggled = value != 0
            alarm_cfg.auto_resume_on_presence_seen_after_exit_tunnel = toggled
        toggle.stateChanged.connect(toggle_changed)
        grid_layout.addWidget(toggle, cur_row, 1)
        cur_row += 1

        grid_layout.addWidget(QLabel("Presence missing delay after exit tunnel:"), cur_row, 0)
        spinbox = QDoubleSpinBox()
        spinbox.setRange(0, 120)
        spinbox.setDecimals(1)
        spinbox.setValue(alarm_cfg.tunnel_to_cage_presence_missing_delay)
        spinbox.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        def value_changed(value):
            alarm_cfg.tunnel_to_cage_presence_missing_delay = value
        spinbox.valueChanged.connect(value_changed)
        grid_layout.addWidget(spinbox, cur_row, 1)
        cur_row += 1

        #
        cur_row = 0
        cur_col = 2
        #
        grid_layout.addWidget(QLabel("<b>Global Mouse Presence</b>"), cur_row, cur_col)
        cur_row += 1
        spinbox = QSpinBox()
        spinbox.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        spinbox.setRange(0, 100)
        spinbox.setValue(behavior_cfg.mouse_presence.presence_missing_delay)
        def value_changed(value):
            behavior_cfg.mouse_presence.presence_missing_delay = value
            model.behavior.algorithm.presence_missing_delay = value
        spinbox.valueChanged.connect(value_changed)
        grid_layout.addWidget(QLabel("Missing delay:"), cur_row, cur_col)
        grid_layout.addWidget(spinbox, cur_row, cur_col + 1)
        cur_row += 1

        grid_layout.addWidget(QLabel("<b>Load Cell Monitor</b>"), cur_row, cur_col)
        cur_row += 1

        spinbox = QSpinBox()
        spinbox.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        spinbox.setRange(0, 100)
        spinbox.setValue(load_cell_monitor.config.thrashing_min_ptp_change_count)
        def value_changed(value):
            load_cell_monitor.config.thrashing_min_ptp_change_count = value
        spinbox.valueChanged.connect(value_changed)
        grid_layout.addWidget(QLabel("Thrashing PTP change count:"), cur_row, cur_col)
        grid_layout.addWidget(spinbox, cur_row, cur_col + 1)
        cur_row += 1

        spinbox = QDoubleSpinBox()
        spinbox.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        spinbox.setDecimals(1)
        spinbox.setRange(0, 100)
        spinbox.setValue(load_cell_monitor.config.thrashing_var_weight_threshold_min)
        def value_changed(value):
            load_cell_monitor.config.thrashing_var_weight_threshold_min = value
        spinbox.valueChanged.connect(value_changed)
        grid_layout.addWidget(QLabel("Thrashing min threshold:"), cur_row, cur_col)
        grid_layout.addWidget(spinbox, cur_row, cur_col + 1)
        cur_row += 1

        spinbox = QDoubleSpinBox()
        spinbox.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        spinbox.setDecimals(1)
        spinbox.setRange(0, 100)
        spinbox.setValue(load_cell_monitor.config.thrashing_var_weight_threshold_max)
        def value_changed(value):
            load_cell_monitor.config.thrashing_var_weight_threshold_max = value
        spinbox.valueChanged.connect(value_changed)
        grid_layout.addWidget(QLabel("Thrashing max threshold:"), cur_row, cur_col)
        grid_layout.addWidget(spinbox, cur_row, cur_col + 1)
        cur_row += 1

        grid_layout.addWidget(QLabel("<b>Audio Monitor</b>"), cur_row, cur_col)
        cur_row += 1

        spinbox = QDoubleSpinBox()
        spinbox.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        spinbox.setDecimals(1)
        spinbox.setRange(0, 200)
        spinbox.setValue(behavior_cfg.audio.threshold_db)
        def value_changed(value):
            behavior_cfg.audio.threshold_db = value
        spinbox.valueChanged.connect(value_changed)
        grid_layout.addWidget(QLabel("Threshold db:"), cur_row, cur_col)
        grid_layout.addWidget(spinbox, cur_row, cur_col + 1)
        cur_row += 1

        line_edit = QLineEdit()
        line_edit.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        line_edit.setText(str(behavior_cfg.audio.bins_list))
        def value_changed(line_edit=line_edit):
            value = line_edit.text()
            try:
                value = ast.literal_eval(value)
                if not isinstance(value, (list, tuple)) or not all(isinstance(v, int) for v in value):
                    raise ValueError(f"not a list or not integers")
            except Exception as err:
                QMessageBox.critical(self, "Invalid", f"Invalid value for bins list: {err}")
            else:
                behavior_cfg.audio.bins_list = list(value)
        line_edit.editingFinished.connect(value_changed)
        grid_layout.addWidget(QLabel("Bins list:"), cur_row, cur_col)
        grid_layout.addWidget(line_edit, cur_row, cur_col + 1)
        cur_row += 1

        tab = QWidget(None)
        tab.setLayout(main_layout)
        tab.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        return tab

    #

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
