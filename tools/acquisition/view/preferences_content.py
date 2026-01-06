import ast
import copy
import logging
import math

import verboselogs
from PySide6 import QtCore
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QFormLayout, QLineEdit, QComboBox, QLabel, QHBoxLayout, QPushButton,
                               QFileDialog, QTabWidget, QVBoxLayout, QCheckBox, QDoubleSpinBox, QSpinBox, QGridLayout,
                               QLayout, QSizePolicy, QMessageBox)

from autotrainer.core.analysis.global_animal_presence_monitor import GlobalAnimalPresenceMonitor
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

        tabs = self._tabs = QTabWidget(self)

        self._general_tab = self._create_general_tab()
        tabs.addTab(self._general_tab, "General")

        self._behavior_tab = self._create_behavior_tab()
        tabs.addTab(self._behavior_tab, "Behavior")

        self._analysis_tab = self._create_analysis_tab()
        tabs.addTab(self._analysis_tab, "Analysis")

        self._detectors_tab = self._create_detectors_tab()
        tabs.addTab(self._detectors_tab, "Detectors")

        self._alarms_tab = self._create_alarms_tab()
        tabs.addTab(self._alarms_tab, "Alarms")

        self._advanced_tab = self._create_advanced_tab()
        tabs.addTab(self._advanced_tab, "Advanced")

        layout = QVBoxLayout()
        layout.addWidget(self._tabs)

        self.setLayout(layout)

        self._update_tab_sizes()
        tabs.currentChanged.connect(self._update_tab_sizes)

    def _update_tab_sizes(self):
        tabs = self._tabs
        cur_idx = tabs.currentIndex()
        for i in range(tabs.count()):
            widget = tabs.widget(i)
            if i != cur_idx:
                widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
            else:
                # Set desired size policy for the active tab
                widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        # Ensure the layout updates
        cur_widget = tabs.currentWidget()
        cur_widget.updateGeometry()
        tabs.minimumSize = cur_widget.minimumSizeHint
        self.updateGeometry()
        self.update()

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

        states_refresh = []
        add_enabled_state = states_refresh.append
        def refresh_enabled_states():
            pm = behavior.system_machine.pellet
            logger.debug("delivery=%s cover=%s can_cover=%s can_release=%s can_send=%s can_load=%s can_analysis=%s pm.covered=%s",
                         algo.pellet_delivery_enabled, algo.pellet_cover_enabled,
                         algo.can_cover_pellet(), algo.can_release_pellet(),
                         algo.can_send_pellet(), algo.can_load_pellet(),
                         algo.can_perform_intersession_analysis(), pm._covered_state)
            for r in states_refresh:
                r()

        main_layout = QVBoxLayout()
        main_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        top_layout = QVBoxLayout()
        top_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        analysis_layout = QHBoxLayout()
        analysis_layout.addWidget(QLabel("Live Analysis:"))
        toggle = self._inference_enabled_toggle = QSwitch()
        toggle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        toggle.setToolTip("Enables real-time pose inference during live sessions (mouse in tunnel).")
        toggle.setChecked(app_model.inference.is_enabled)
        def inference_enabled_state_changed(x: int):
            enabled = x != 0
            app_model.inference.is_enabled = enabled
            refresh_enabled_states()
        toggle.stateChanged.connect(inference_enabled_state_changed)  # after setChecked
        analysis_layout.addWidget(toggle)
        analysis_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        top_layout.addLayout(analysis_layout)
        #
        inference_model_layout = QHBoxLayout()
        inference_model_layout.addWidget(QLabel("Inference model:"))

        line_edit = self._inference_model_edit = QLineEdit(None, None)
        add_enabled_state(lambda: self._inference_model_edit.setEnabled(self._inference_enabled_toggle.isChecked()))
        line_edit.setText(self._app_model.inference.model_location)
        line_edit.textChanged.connect(self._inference_model_changed)
        inference_model_layout.addWidget(self._inference_model_edit)

        button = self._select_model_button = QPushButton("Select...")
        self._select_model_button.setEnabled(self._inference_enabled_toggle.isChecked())
        button.clicked.connect(lambda: self._browse_for_location("inference_model"))
        inference_model_layout.addWidget(button)
        inference_model_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        #
        top_layout.addLayout(inference_model_layout)
        main_layout.addLayout(top_layout)
        #
        cur_row = 0
        cur_col = 0
        grid_layout = QGridLayout()
        def add_empty(min_width=0, min_height=0):
            nonlocal cur_row, cur_col
            empty = QWidget()
            empty.setContentsMargins(min_width, min_height, 0, 0)
            empty.setMinimumWidth(min_width)
            empty.setMinimumHeight(min_height)
            grid_layout.addWidget(empty, cur_row, cur_col)
            if min_width != 0:
                cur_col += 1
            if min_height != 0:
                cur_row += 1
        add_height_separator = lambda: add_empty(min_height=6)
        add_width_separator = lambda: add_empty(min_width=6)

        grid_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        grid_layout.setSpacing(4)
        grid_layout.setHorizontalSpacing(10)
        main_layout.addLayout(grid_layout)

        add_empty(min_height=4)

        grid_layout.addWidget(QLabel("Deliver Pellets:"), cur_row, cur_col)
        toggle = self._deliver_pellet_toggle = QSwitch()
        add_enabled_state(lambda: self._deliver_pellet_toggle.setEnabled(self._inference_enabled_toggle.isChecked()))
        toggle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        toggle.setToolTip(
            "Enables pellet load-send-release cycles based on pellet detection and related factors.")
        toggle.setChecked(algo.pellet_delivery_enabled)
        grid_layout.addWidget(toggle, cur_row, cur_col + 1)
        def deliver_pellet_state_changed(x: int):
            enabled = x != 0
            algo.pellet_delivery_enabled = enabled
            refresh_enabled_states()
        toggle.stateChanged.connect(deliver_pellet_state_changed)
        cur_row += 1
        #
        # pelletDelivery:maxPelletMissingSeconds
        grid_layout.addWidget(QLabel("Pellet missing seconds:"), cur_row, cur_col)
        spinbox = self._deliver_pellet_missing_seconds_spinbox = QDoubleSpinBox()
        spinbox.setToolTip("Delay pellet missing after which load pellet can be executed")
        add_enabled_state(lambda: self._deliver_pellet_missing_seconds_spinbox.setEnabled(
            self._deliver_pellet_toggle.isEnabled() and self._deliver_pellet_toggle.isChecked()
        ))
        spinbox.setValue(algo.pellet_missing_time)
        spinbox.setDecimals(2)
        spinbox.setSingleStep(0.05)
        def max_pellet_missing_seconds_changed(value):
            algo.pellet_missing_time = value
        spinbox.valueChanged.connect(max_pellet_missing_seconds_changed)
        grid_layout.addWidget(spinbox, cur_row, cur_col + 1)
        cur_row += 1
        #
        grid_layout.addWidget(QLabel("Cover Pellets:"), cur_row, cur_col)
        toggle = self._pellet_cover_toggle = QSwitch()
        toggle.setToolTip(
            "Covers the pellet when the mouse is not in the tunnel.  Release then generates a tone when the tunnel is "
            "entered.")
        add_enabled_state(lambda: self._pellet_cover_toggle.setEnabled(
            self._deliver_pellet_toggle.isEnabled() and self._deliver_pellet_toggle.isChecked()
        ))
        toggle.setChecked(algo.pellet_cover_enabled)
        toggle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        def pellet_cover_toggle_state_changed(x: int):
            enabled = x != 0
            algo.pellet_cover_enabled = enabled
            refresh_enabled_states()
        toggle.stateChanged.connect(pellet_cover_toggle_state_changed)
        grid_layout.addWidget(toggle, cur_row, cur_col + 1)
        cur_row += 1
        #
        # pelletDelivery:pelletHandUncoverDistance [1]
        grid_layout.addWidget(QLabel("Pellet-hand minimum distance:"), cur_row, cur_col)
        toggle = self._pellet_hand_uncover_distance_toggle = QSwitch()
        toggle.setToolTip("Pellet-hand distance below which cover is released")
        add_enabled_state(lambda: self._pellet_hand_uncover_distance_toggle.setEnabled(
            self._deliver_pellet_toggle.isEnabled()
            and self._deliver_pellet_toggle.isChecked()
            and self._pellet_cover_toggle.isChecked()
        ))
        toggle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        toggle.setChecked(algo.pellet_hand_uncover_distance is not None)
        def toggle_pellet_hand_uncover_distance_changed(value: int):
            enabled = value != 0
            if enabled:
                value = PelletDeliveryConfiguration.pellet_hand_uncover_distance or 10
                self._pellet_hand_uncover_distance_spinbox.setValue(value)
            else:
                algo.pellet_hand_uncover_distance = None
            refresh_enabled_states()
        toggle.stateChanged.connect(toggle_pellet_hand_uncover_distance_changed)
        grid_layout.addWidget(toggle, cur_row, cur_col + 1)
        cur_row += 1

        pellet_hand_uncover_label = QLabel("Pellet-hand uncover distance (mm) :")
        grid_layout.addWidget(pellet_hand_uncover_label, cur_row, cur_col)
        spinbox = self._pellet_hand_uncover_distance_spinbox = QDoubleSpinBox()
        add_enabled_state(lambda s=spinbox, t=self._pellet_hand_uncover_distance_toggle:
            s.setEnabled(t.isEnabled() and t.isChecked())
        )
        if algo.pellet_hand_uncover_distance is not None:
            spinbox.setValue(algo.pellet_hand_uncover_distance)
        spinbox.setMinimum(0)
        spinbox.setMaximum(100)
        spinbox.setDecimals(1)
        spinbox.setSingleStep(0.5)
        def pellet_hand_uncover_distance_changed(value):
            algo.pellet_hand_uncover_distance = value
        spinbox.valueChanged.connect(pellet_hand_uncover_distance_changed)
        grid_layout.addWidget(spinbox, cur_row, cur_col + 1)
        cur_row += 1
        #
        add_height_separator()
        grid_layout.addWidget(QLabel("Intersession Pellet Shift:"), cur_row, cur_col)
        toggle = self._allow_intersession_shift_toggle = QSwitch()
        toggle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        toggle.setToolTip("Enables adjustment of the pellet delivery position based on post-session reach analysis.")
        add_enabled_state(lambda: self._allow_intersession_shift_toggle.setEnabled(self._inference_enabled_toggle.isChecked()))
        toggle.setChecked(algo.intersession_pellet_shift_enabled)
        def allow_intersession_shift_toggle_state_changed(x: int):
            enabled = x != 0
            if enabled:
                behavior.algorithm.intersession_enabled = True
            algo.intersession_pellet_shift_enabled = enabled
        toggle.stateChanged.connect(allow_intersession_shift_toggle_state_changed)
        grid_layout.addWidget(toggle, cur_row, cur_col + 1)
        cur_row += 1
        #
        grid_layout.addWidget(QLabel("Auto-correct motors drift:"), cur_row, cur_col)
        toggle = self._auto_correct_motors_drift_toggle = QSwitch()
        add_enabled_state(lambda: self._auto_correct_motors_drift_toggle.setEnabled(self._inference_enabled_toggle.isChecked()))
        toggle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        toggle.setChecked(self._app_model.behavior.algorithm.auto_correct_motors_drift)
        def auto_correct_motors_drift_toggle_changed(value: int):
            enabled = value != 0
            logger.verbose("auto_correct_motors_drift_toggle_changed: %s", enabled)
            self._app_model.behavior.algorithm.auto_correct_motors_drift = enabled
        toggle.stateChanged.connect(auto_correct_motors_drift_toggle_changed)
        grid_layout.addWidget(toggle, cur_row, cur_col + 1)
        cur_row += 1

        #
        add_height_separator()
        grid_layout.addWidget(QLabel("<b>Triangle-pellet distance for pellet too far detection:</b>"), cur_row, cur_col)
        toggle = self._use_triangle_pellet_distance_toggle = QSwitch()
        add_enabled_state(lambda: self._use_triangle_pellet_distance_toggle.setEnabled(self._inference_enabled_toggle.isChecked()))
        toggle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        toggle.setChecked(algo.use_triangle_pellet_distance_too_far)
        def use_triangle_pellet_distance_changed(value):
            enabled = value != 0
            algo.use_triangle_pellet_distance_too_far = enabled
            refresh_enabled_states()
        self._use_triangle_pellet_distance_toggle.stateChanged.connect(use_triangle_pellet_distance_changed)
        grid_layout.addWidget(toggle, cur_row, cur_col + 1)
        cur_row += 1
        #
        grid_layout.addWidget(QLabel("Maximum expected distance (mm):"), cur_row, cur_col)
        spinbox = self._triangle_pellet_expected_distance_spinbox = QDoubleSpinBox()
        add_enabled_state(lambda s=spinbox, t=self._use_triangle_pellet_distance_toggle:
            s.setEnabled(t.isEnabled() and t.isChecked())
        )
        spinbox.setRange(0, 99)
        spinbox.setValue(algo.triangle_pellet_expected_distance)
        def triangle_pellet_expected_distance_changed(value):
            algo.triangle_pellet_expected_distance = value
        spinbox.valueChanged.connect(triangle_pellet_expected_distance_changed)
        grid_layout.addWidget(spinbox, cur_row, cur_col + 1)
        cur_row += 1
        #
        grid_layout.addWidget(QLabel("Triangle-Pellet diff too far threshold (mm):"), cur_row, cur_col)
        spinbox = self._triangle_pellet_diff_too_far_threshold_spinbox = QDoubleSpinBox()
        add_enabled_state(lambda s=spinbox, t=self._use_triangle_pellet_distance_toggle:
            s.setEnabled(t.isEnabled() and t.isChecked())
        )
        spinbox.setRange(0, 20)
        spinbox.setValue(algo.triangle_pellet_diff_too_far_threshold)
        def triangle_pellet_diff_too_far_threshold_changed(value):
            algo.triangle_pellet_diff_too_far_threshold = value
        spinbox.valueChanged.connect(triangle_pellet_diff_too_far_threshold_changed)
        grid_layout.addWidget(spinbox, cur_row, cur_col + 1)
        cur_row += 1

        #
        add_height_separator()
        grid_layout.addWidget(QLabel("<b>Auto-close gate during intersession:</b>"), cur_row, cur_col)
        auto_close_gate_cfg = algo.auto_close_gate_on_intersession_config
        toggle = self._auto_close_gate_during_intersession_toggle = QSwitch()
        toggle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        toggle.setChecked(auto_close_gate_cfg.enabled)
        def toggle_changed(value):
            enabled = value != 0
            auto_close_gate_cfg.enabled = enabled
            refresh_enabled_states()
        self._auto_close_gate_during_intersession_toggle.stateChanged.connect(toggle_changed)

        grid_layout.addWidget(toggle, cur_row, cur_col + 1)
        cur_row += 1

        grid_layout.addWidget(QLabel("session minimum duration (sec.):"), cur_row, cur_col)
        spinbox = self._auto_close_gate_sess_minimum_duration_spinbox = QDoubleSpinBox()
        add_enabled_state(lambda: self._auto_close_gate_sess_minimum_duration_spinbox.setEnabled(
            self._auto_close_gate_during_intersession_toggle.isChecked()
        ))
        spinbox.setRange(0, max(1_000_000, auto_close_gate_cfg.session_min_duration))
        spinbox.setDecimals(1)
        spinbox.setValue(auto_close_gate_cfg.session_min_duration)
        def spinbox_value_changed(value):
            auto_close_gate_cfg.session_min_duration = value
        spinbox.valueChanged.connect(spinbox_value_changed)
        grid_layout.addWidget(spinbox, cur_row, cur_col + 1)
        cur_row += 1

        grid_layout.addWidget(QLabel("delay after cage enter to close (sec.):"), cur_row, cur_col)
        spinbox = QDoubleSpinBox()
        add_enabled_state(lambda s=spinbox: s.setEnabled(
            self._auto_close_gate_during_intersession_toggle.isChecked()
        ))
        spinbox.setRange(0, 60)
        spinbox.setDecimals(1)
        spinbox.setValue(auto_close_gate_cfg.delay_after_cage_enter)
        def spinbox_value_changed(value):
            auto_close_gate_cfg.delay_after_cage_enter = value
        spinbox.valueChanged.connect(spinbox_value_changed)
        grid_layout.addWidget(spinbox, cur_row, cur_col + 1)
        cur_row += 1

        # right part:
        cur_row = 0
        cur_col = 2

        add_empty(min_width=4, min_height=4)

        # headClamp: autoClampReleaseToneFreq
        label = QLabel("<b>Auto-Clamp:</b>")
        grid_layout.addWidget(label, cur_row, cur_col)
        toggle = self._auto_clamp_enabled_toggle = QSwitch()
        toggle.setChecked(algo.head_fixation_enabled)
        # auto-clamp enabled:
        def toggle_changed(value):
            enabled = value != 0
            algo.head_fixation_enabled = enabled
            refresh_enabled_states()
        toggle.stateChanged.connect(toggle_changed)
        grid_layout.addWidget(toggle, cur_row, cur_col + 1)
        cur_row += 1
        #
        grid_layout.addWidget(QLabel("Threshold:"), cur_row, cur_col)
        spinbox = self._auto_clamp_threshold_spinbox = QSpinBox(None)
        add_enabled_state(lambda s=spinbox, t=toggle: s.setEnabled(t.isChecked()))
        spinbox.setValue(analysis.headbar_pressure_monitor.load_cell_engaged_threshold)
        spinbox.setMinimum(0)
        spinbox.setMaximum(1023)
        spinbox.setWrapping(False)
        def update_headbar_pressure_threshold(value):
            analysis.headbar_pressure_monitor.load_cell_engaged_threshold = value
        spinbox.valueChanged.connect(update_headbar_pressure_threshold)
        spinbox.setToolTip("A value that adjusts the sensitivity of the headbar detector for it to be considered engaged.")
        grid_layout.addWidget(spinbox, cur_row, cur_col + 1)
        cur_row += 1

        grid_layout.addWidget(QLabel("Release tone freq (Hz) :"), cur_row, cur_col)
        spinbox = self._auto_clamp_release_tone_freq = QSpinBox()
        add_enabled_state(lambda s=spinbox, t=toggle: s.setEnabled(t.isChecked()))
        def auto_clamp_release_tone_freq_changed(value):
            algo.auto_clamp_release_tone_freq = value
        spinbox.setMinimum(0)
        spinbox.setMaximum(100_000)
        spinbox.setValue(algo.auto_clamp_release_tone_freq)
        spinbox.valueChanged.connect(auto_clamp_release_tone_freq_changed)
        grid_layout.addWidget(spinbox, cur_row, cur_col + 1)
        cur_row += 1

        # headClamp:autoClampReleaseToneDelay
        grid_layout.addWidget(QLabel("Release tone delay (sec.) :"), cur_row, cur_col)
        spinbox = self._auto_clamp_release_tone_delay = QDoubleSpinBox()
        add_enabled_state(lambda s=spinbox, t=toggle: s.setEnabled(t.isChecked()))
        def auto_clamp_release_tone_delay_changed(value):
            algo.auto_clamp_release_tone_delay = value
        spinbox.setValue(algo.auto_clamp_release_tone_delay)
        spinbox.valueChanged.connect(auto_clamp_release_tone_delay_changed)
        grid_layout.addWidget(spinbox, cur_row, cur_col + 1)
        cur_row += 1

        # headClamp:autoClampNoActivityReleaseDelay
        grid_layout.addWidget(QLabel("No-activity release delay (sec.) :"), cur_row, cur_col)
        spinbox = self._auto_clamp_no_activity_release_delay = QDoubleSpinBox()
        add_enabled_state(lambda s=spinbox, t=toggle: s.setEnabled(t.isChecked()))
        def auto_clamp_no_activity_release_delay_changed(value):
            algo.auto_clamp_no_activity_release_delay = value
        spinbox.setValue(algo.auto_clamp_no_activity_release_delay)
        spinbox.valueChanged.connect(auto_clamp_no_activity_release_delay_changed)
        grid_layout.addWidget(spinbox, cur_row, cur_col + 1)
        cur_row += 1

        # headClamp:autoClampReleaseLoadCount
        grid_layout.addWidget(QLabel("Release load count:"), cur_row, cur_col)
        spinbox = self._auto_clamp_release_load_count = QSpinBox()
        add_enabled_state(lambda s=spinbox, t=toggle: s.setEnabled(t.isChecked()))
        spinbox.setMinimum(0)
        spinbox.setMaximum(1_000_000)
        def auto_clamp_release_load_count_changed(value):
            algo.auto_clamp_release_load_count = value
        spinbox.setValue(algo.auto_clamp_release_load_count)
        spinbox.valueChanged.connect(auto_clamp_release_load_count_changed)
        grid_layout.addWidget(spinbox, cur_row, cur_col + 1)
        cur_row += 1
        #
        grid_layout.addWidget(QLabel("Before re-engage delay (sec.):"), cur_row, cur_col)
        spinbox = self._auto_clamp_before_reengage_delay = QDoubleSpinBox()
        add_enabled_state(lambda s=spinbox, t=toggle: s.setEnabled(t.isChecked()))
        spinbox.setRange(0, 600)
        spinbox.setValue(algo.auto_clamp_before_reengage_delay)
        spinbox.setDecimals(1)
        def auto_clamp_before_reengage_delay_changed(value):
            algo.auto_clamp_before_reengage_delay = value
        spinbox.valueChanged.connect(auto_clamp_before_reengage_delay_changed)
        grid_layout.addWidget(spinbox, cur_row, cur_col + 1)
        #
        # to enable/disable the inference dependant sub-widgets:
        refresh_enabled_states()

        for r_idx in range(grid_layout.rowCount()):
            for c_idx in range(grid_layout.columnCount()):
                i = grid_layout.itemAtPosition(r_idx, c_idx)
                if i is not None:
                    w = i.widget()
                    if isinstance(w, QSwitch):
                        w.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                    elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
                        # w.setAlignment(Qt.AlignmentFlag.AlignRight)
                        w.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        #
        tab = QWidget()
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

        tab = QWidget(None)
        tab.setLayout(form_layout)

        return tab

    def _create_detectors_tab(self):
        model = self._app_model
        analysis = model.analysis
        load_cell_monitor = analysis.load_cell_monitor

        top_layout = QHBoxLayout()

        left_layout = QVBoxLayout()
        top_layout.addLayout(left_layout)

        left_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        grid_layout = QGridLayout()
        grid_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        grid_layout.setSpacing(4)
        grid_layout.setHorizontalSpacing(10)
        left_layout.addLayout(grid_layout)

        cur_row = 0
        cur_col = 0

        if GlobalAnimalPresenceMonitor.feature_enabled:
            grid_layout.addWidget(QLabel("<b>Global Animal Presence</b>"), cur_row, cur_col)
            cur_row += 1

            grid_layout.addWidget(QLabel("Missing delay (hours):"), cur_row, cur_col)
            spinbox = QDoubleSpinBox()
            spinbox.setRange(0, 24 * 2)  # 2 days
            spinbox.setDecimals(2)
            spinbox.setSingleStep(1)
            spinbox.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            spinbox.setValue(analysis.global_animal_presence_monitor.config.presence_missing_delay_hours)
            def value_changed(value):
                analysis.global_animal_presence_monitor.config.presence_missing_delay_hours = value
                analysis.global_animal_presence_monitor.refresh_state()
            spinbox.valueChanged.connect(value_changed)
            grid_layout.addWidget(spinbox, cur_row, cur_col + 1)
            cur_row += 1

        #
        label = QLabel("<b>Load Cell Thrash Detector</b>")
        grid_layout.addWidget(label, cur_row, cur_col)
        cur_row += 1

        grid_layout.addWidget(QLabel("Thrashing PTP change count:"), cur_row, cur_col)
        spinbox = QSpinBox()
        if cur_row != 1:
            assert GlobalAnimalPresenceMonitor.feature_enabled
            label.setContentsMargins(0, 10, 0, 0)
            spinbox.setContentsMargins(0, 10, 0, 0)
        spinbox.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        spinbox.setRange(0, 100)
        spinbox.setValue(load_cell_monitor.config.thrashing_min_ptp_change_count)
        def value_changed(value):
            load_cell_monitor.config.thrashing_min_ptp_change_count = value
        spinbox.valueChanged.connect(value_changed)
        grid_layout.addWidget(spinbox, cur_row, cur_col + 1)
        cur_row += 1

        grid_layout.addWidget(QLabel("Thrashing min threshold:"), cur_row, cur_col)
        spinbox = QDoubleSpinBox()
        spinbox.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        spinbox.setDecimals(1)
        spinbox.setRange(0, 100)
        spinbox.setValue(load_cell_monitor.config.thrashing_var_weight_threshold_min)
        def value_changed(value):
            load_cell_monitor.config.thrashing_var_weight_threshold_min = value
        spinbox.valueChanged.connect(value_changed)
        grid_layout.addWidget(spinbox, cur_row, cur_col + 1)
        cur_row += 1

        grid_layout.addWidget(QLabel("Thrashing max threshold:"), cur_row, cur_col)
        spinbox = QDoubleSpinBox()
        spinbox.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        spinbox.setDecimals(1)
        spinbox.setRange(0, 100)
        spinbox.setValue(load_cell_monitor.config.thrashing_var_weight_threshold_max)
        def value_changed(value):
            load_cell_monitor.config.thrashing_var_weight_threshold_max = value
        spinbox.valueChanged.connect(value_changed)
        grid_layout.addWidget(spinbox, cur_row, cur_col + 1)
        cur_row += 1

        label = QLabel("<b>Audio Detector</b>")
        label.setContentsMargins(0, 10, 0, 0)
        grid_layout.addWidget(label, cur_row, cur_col)
        cur_row += 1

        grid_layout.addWidget(QLabel("Threshold db:"), cur_row, cur_col)
        spinbox = QDoubleSpinBox()
        spinbox.setContentsMargins(0, 10, 0, 0)
        spinbox.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        spinbox.setDecimals(1)
        spinbox.setRange(0, 200)
        spinbox.setValue(analysis.audio_thrashing_monitor.config.threshold_db)
        def value_changed(value):
            analysis.audio_thrashing_monitor.config.threshold_db = value
        spinbox.valueChanged.connect(value_changed)
        grid_layout.addWidget(spinbox, cur_row, cur_col + 1)
        cur_row += 1

        grid_layout.addWidget(QLabel("Bins list:"), cur_row, cur_col)
        line_edit = QLineEdit()
        line_edit.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        line_edit.setText(str(analysis.audio_thrashing_monitor.config.bins_list))
        def value_changed(line_edit=line_edit):
            value = line_edit.text()
            try:
                value = ast.literal_eval(value)
                if not isinstance(value, (list, tuple)) or not all(isinstance(v, int) for v in value):
                    raise ValueError(f"not a list or not integers")
            except Exception as err:
                QMessageBox.critical(self, "Invalid", f"Invalid value for bins list: {err}")
            else:
                analysis.audio_thrashing_monitor.config.bins_list = list(value)
        line_edit.editingFinished.connect(value_changed)
        grid_layout.addWidget(line_edit, cur_row, cur_col + 1)
        cur_row += 1

        right_layout = QFormLayout()

        right_layout.addRow("<b>TopCam Presence:</b>", QWidget())

        spinbox = self._presence_sum_percent_threshold_spinbox = QDoubleSpinBox()
        spinbox.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        spinbox.setRange(0, 100)
        spinbox.setSingleStep(0.1)
        spinbox.setDecimals(1)
        spinbox.setValue(model.top_camera_presence_detection.pc_threshold)
        def value_changed(value: float):
            model.top_camera_presence_detection.pc_threshold = value
        spinbox.valueChanged.connect(value_changed)
        right_layout.addRow("% threshold:", spinbox)

        spinbox = QDoubleSpinBox()
        spinbox.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        spinbox.setRange(0, 100)
        spinbox.setSingleStep(0.1)
        spinbox.setDecimals(1)
        spinbox.setValue(model.top_camera_presence_detection.pc_high_exclude_threshold)
        def value_changed(value: float):
            model.top_camera_presence_detection.pc_high_exclude_threshold = value
        spinbox.valueChanged.connect(value_changed)
        right_layout.addRow("high-% exclude threshold:", spinbox)

        spinbox = QSpinBox()
        spinbox.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        spinbox.setRange(0, 255)
        spinbox.setSingleStep(1)
        spinbox.setValue(model.top_camera_presence_detection.mask_lower_zero)
        def value_changed(value: float):
            model.top_camera_presence_detection.mask_lower_zero = value
        spinbox.valueChanged.connect(value_changed)
        right_layout.addRow("Mask Lower Zero:", spinbox)

        spinbox = QDoubleSpinBox()
        spinbox.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        spinbox.setRange(0, 100)
        spinbox.setSingleStep(0.1)
        spinbox.setDecimals(1)
        spinbox.setValue(model.top_camera_presence_detection.max_delay_skip_threshold)
        def value_changed(value: float):
            model.top_camera_presence_detection.max_delay_skip_threshold = value
        spinbox.valueChanged.connect(value_changed)
        right_layout.addRow("Max Delay Skip Seconds:", spinbox)

        top_layout.addLayout(right_layout)

        tab = QWidget(None)
        tab.setLayout(top_layout)
        tab.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        return tab

    def _create_alarms_tab(self):
        model = self._app_model
        analysis = model.analysis
        alarm_monitor = analysis.emergency_alarm_monitor
        alarm_cfg = analysis.emergency_alarm_monitor.config

        main_layout = QVBoxLayout()
        main_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        label = QLabel("<b>Emergency Alarm Monitor</b>")
        label.setContentsMargins(0, 0, 0, 10)
        main_layout.addWidget(label)

        # not sure why but inner spinboxes are taking their max size while in behavior tab they don't
        # but we use similar layout scheme.
        # Found: behavior tab uses our QSwitch() which has a size hint
        grid_layout = QGridLayout()
        grid_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        grid_layout.setSpacing(4)
        grid_layout.setHorizontalSpacing(10)
        main_layout.addLayout(grid_layout)

        cur_row = 0
        cur_col = 0

        audio_load_cell_sub_widgets = []

        label = QLabel("<b>Use Audio & Load Cell Thrashing Alarm:</b>")
        grid_layout.addWidget(label, cur_row, cur_col)
        toggle = self._use_audio_load_cell_thrashing_toggle = QSwitch()
        toggle.setChecked(alarm_cfg.use_audio_load_cell_thrash)
        toggle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        grid_layout.addWidget(toggle, cur_row, cur_col + 1)
        cur_row += 1

        grid_layout.addWidget(QLabel("Allow auto-resume when cleared:"), cur_row, cur_col)
        toggle = QSwitch()
        audio_load_cell_sub_widgets.append(toggle)
        toggle.setChecked(alarm_cfg.auto_resume_on_audio_load_cell_thrash_resume)
        def toggle_changed(value):
            toggled = value != 0
            cfg = copy.deepcopy(alarm_monitor.config)
            cfg.auto_resume_on_audio_load_cell_thrash_resume = toggled
            alarm_monitor.config = cfg
        toggle.stateChanged.connect(toggle_changed)
        grid_layout.addWidget(toggle, cur_row, cur_col + 1)
        cur_row += 1

        grid_layout.addWidget(QLabel("Thrash aggregate delay (seconds):"), cur_row, cur_col)
        spinbox = QDoubleSpinBox()
        audio_load_cell_sub_widgets.append(spinbox)
        spinbox.setRange(0, 60)
        spinbox.setDecimals(1)
        spinbox.setValue(alarm_cfg.audio_load_cell_thrash_aggregate_delay)
        spinbox.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        def value_changed(value):
            alarm_cfg.audio_load_cell_thrash_aggregate_delay = value
        spinbox.valueChanged.connect(value_changed)
        grid_layout.addWidget(spinbox, cur_row, cur_col + 1)
        cur_row += 1

        grid_layout.addWidget(QLabel("LoadCell thrash % time:"), cur_row, cur_col)
        spinbox = QSpinBox()
        audio_load_cell_sub_widgets.append(spinbox)
        spinbox.setRange(0, 100)
        spinbox.setValue(alarm_cfg.load_cell_thrash_percent_on)
        spinbox.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        def value_changed(value):
            alarm_cfg.load_cell_thrash_percent_on = value
        spinbox.valueChanged.connect(value_changed)
        grid_layout.addWidget(spinbox, cur_row, cur_col + 1)
        cur_row += 1

        grid_layout.addWidget(QLabel("LoadCell thrash count:"), cur_row, cur_col)
        spinbox = QSpinBox()
        audio_load_cell_sub_widgets.append(spinbox)
        spinbox.setRange(0, 100)
        spinbox.setValue(alarm_cfg.load_cell_thrash_count)
        spinbox.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        def value_changed(value):
            alarm_cfg.load_cell_thrash_count = value
        spinbox.valueChanged.connect(value_changed)
        grid_layout.addWidget(spinbox, cur_row, cur_col + 1)
        cur_row += 1

        grid_layout.addWidget(QLabel("Audio thrash % time:"), cur_row, cur_col)
        spinbox = QSpinBox()
        audio_load_cell_sub_widgets.append(spinbox)
        spinbox.setRange(0, 100)
        spinbox.setValue(alarm_cfg.audio_thrash_percent_on)
        spinbox.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        def value_changed(value):
            alarm_cfg.audio_thrash_percent_on = value
        spinbox.valueChanged.connect(value_changed)
        grid_layout.addWidget(spinbox, cur_row, cur_col + 1)
        cur_row += 1

        grid_layout.addWidget(QLabel("Audio thrash count:"), cur_row, cur_col)
        spinbox = QSpinBox()
        audio_load_cell_sub_widgets.append(spinbox)
        spinbox.setRange(0, 100)
        spinbox.setValue(alarm_cfg.audio_thrash_count)
        spinbox.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        def value_changed(value):
            alarm_cfg.audio_thrash_count = value
        spinbox.valueChanged.connect(value_changed)
        grid_layout.addWidget(spinbox, cur_row, cur_col + 1)
        cur_row += 1

        def toggle_changed(value):
            toggled = value != 0
            for w in audio_load_cell_sub_widgets:
                w.setEnabled(toggled)
            if toggled != alarm_monitor.config.use_audio_load_cell_thrash:
                cfg = copy.deepcopy(alarm_monitor.config)
                cfg.use_audio_load_cell_thrash = toggled
                alarm_monitor.config = cfg
        self._use_audio_load_cell_thrashing_toggle.stateChanged.connect(toggle_changed)
        toggle_changed(int(alarm_cfg.use_audio_load_cell_thrash))

        widget = QWidget()
        widget.setMinimumHeight(5)
        grid_layout.addWidget(widget, cur_row, cur_col)
        cur_row += 1

        animal_missing_sub_widgets = []

        label = QLabel("<b>Use Animal Missing Alarm:</b>")
        tooltip_txt = "When not seen in cage after exit tunnel"
        label.setToolTip(tooltip_txt)
        grid_layout.addWidget(label, cur_row, cur_col)
        toggle = self._use_animal_missing_toggle = QSwitch()
        toggle.setToolTip(tooltip_txt)
        toggle.setChecked(alarm_cfg.use_presence_missing_after_exit_tunnel)
        toggle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        grid_layout.addWidget(toggle, cur_row, cur_col + 1)
        cur_row += 1

        grid_layout.addWidget(QLabel("Allow auto-resume when cleared:"), cur_row, cur_col)
        toggle = QSwitch()
        animal_missing_sub_widgets.append(toggle)
        toggle.setChecked(alarm_cfg.auto_resume_on_presence_seen_after_exit_tunnel)
        def toggle_changed(value):
            toggled = value != 0
            cfg = copy.deepcopy(alarm_monitor.config)
            cfg.auto_resume_on_presence_seen_after_exit_tunnel = toggled
            alarm_monitor.config = cfg
        toggle.stateChanged.connect(toggle_changed)
        grid_layout.addWidget(toggle, cur_row, cur_col + 1)
        cur_row += 1

        grid_layout.addWidget(QLabel("Missing delay after exit tunnel (seconds):"), cur_row, cur_col)
        spinbox = QDoubleSpinBox()
        animal_missing_sub_widgets.append(spinbox)
        spinbox.setRange(0, 120)
        spinbox.setDecimals(1)
        spinbox.setValue(alarm_cfg.tunnel_to_cage_presence_missing_delay)
        spinbox.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        def value_changed(value):
            alarm_cfg.tunnel_to_cage_presence_missing_delay = value
        spinbox.valueChanged.connect(value_changed)
        grid_layout.addWidget(spinbox, cur_row, cur_col + 1)
        cur_row += 1

        def toggle_changed(value):
            toggled = value != 0
            for w in animal_missing_sub_widgets:
                w.setEnabled(toggled)
            if toggled != alarm_monitor.config.use_presence_missing_after_exit_tunnel:
                cfg = copy.deepcopy(alarm_monitor.config)
                cfg.use_presence_missing_after_exit_tunnel = toggled
                alarm_monitor.config = cfg
        self._use_animal_missing_toggle.stateChanged.connect(toggle_changed)
        toggle_changed(int(alarm_cfg.use_presence_missing_after_exit_tunnel))

        # right side:

        cur_row = 0
        cur_col = 2

        use_external_doors_sub_widgets = []
        grid_layout.addWidget(QLabel("<b>Use External Doors Open:</b>"), cur_row, cur_col)
        toggle = self._use_external_doors_open_toggle = QSwitch()
        toggle.setToolTip(tooltip_txt)
        toggle.setChecked(alarm_cfg.use_external_doors_open)
        toggle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        grid_layout.addWidget(toggle, cur_row, cur_col + 1)
        cur_row += 1

        grid_layout.addWidget(QLabel("Allow auto-resume when cleared:"), cur_row, cur_col)
        toggle = QSwitch()
        use_external_doors_sub_widgets.append(toggle)
        toggle.setChecked(alarm_cfg.auto_resume_on_external_doors_close)
        def toggle_changed(value):
            toggled = value != 0
            cfg = copy.deepcopy(alarm_monitor.config)
            cfg.auto_resume_on_external_doors_close = toggled
            alarm_monitor.config = cfg
        toggle.stateChanged.connect(toggle_changed)
        grid_layout.addWidget(toggle, cur_row, cur_col + 1)
        cur_row += 1

        grid_layout.addWidget(QLabel("Trigger Open delay (seconds):"), cur_row, cur_col)
        spinbox = QDoubleSpinBox()
        use_external_doors_sub_widgets.append(spinbox)
        spinbox.setRange(0, 3600)
        spinbox.setDecimals(1)
        spinbox.setValue(analysis.external_doors_monitor.config.trigger_open_delay)
        spinbox.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        def value_changed(value):
            analysis.external_doors_monitor.config.trigger_open_delay = value
            analysis.external_doors_monitor.refresh_state()
        spinbox.valueChanged.connect(value_changed)
        grid_layout.addWidget(spinbox, cur_row, cur_col + 1)
        cur_row += 1

        def toggle_changed(value):
            toggled = value != 0
            for w in use_external_doors_sub_widgets:
                w.setEnabled(toggled)
            if toggled != alarm_monitor.config.use_external_doors_open:
                cfg = copy.deepcopy(alarm_monitor.config)
                cfg.use_external_doors_open = toggled
                alarm_monitor.config = cfg
        self._use_external_doors_open_toggle.stateChanged.connect(toggle_changed)
        toggle_changed(int(alarm_cfg.use_external_doors_open))

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
