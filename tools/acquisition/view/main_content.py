import time
import typing
from typing import Tuple

from PySide6 import QtCore
from PySide6.QtCore import QTimer, Slot, Signal, Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QStackedLayout, QWidget, QSizePolicy

from autotrainer.behavior import TrainingMode
from autotrainer.behavior.behavior_algorithm import BehaviorAlgoProps
from autotrainer.core import Offset3DTuple
from autotrainer.core.logging import get_verbose_logger
from autotrainer.inference import PoseResponse, PoseAlgorithm, InferenceStatus
from autotrainer.pyside import Separator, CardWidget

from tools.acquisition.model.app_model import AppModel
from tools.acquisition.view.alarm_content import AlarmContent
from tools.acquisition.view.analysis_content import AnalysisContent
from tools.acquisition.view.content_widget import ContentWidget
from tools.acquisition.view.behavior_content import BehaviorContent
from tools.acquisition.view.camera_content import CameraContent
from tools.acquisition.view.diagnostics_content import DiagnosticsContent
from tools.acquisition.view.hardware_control_content import HardwareControlContent
from tools.acquisition.view.hardware_status_content import HardwareStatusContent

logger = get_verbose_logger(__name__)


class MainContent(ContentWidget):

    training_mode_changed = Signal(TrainingMode)

    def __init__(self, app_model: AppModel):
        super().__init__()

        self._app_model = app_model

        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("MainContent")
        self.setStyleSheet("#MainContent {background-color: #f7f7f7}")

        self._content_widgets: typing.List[ContentWidget] = list()

        self.setContentsMargins(0, 0, 0, 0)

        main_layout = self._main_layout = QVBoxLayout()
        self.setLayout(main_layout)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(4)

        self._top_widget_manual = self._create_top_widget_manual()
        main_layout.addWidget(self._top_widget_manual)

        # Second row - behavior and analysis
        self._mid_stacked_layout = QStackedLayout()
        main_layout.addLayout(self._mid_stacked_layout)

        self._mid_widget_manual = self._create_mid_widget_manual(app_model)
        self._mid_stacked_layout.addWidget(self._mid_widget_manual)
        self._mid_protocol_phase_widget = self._create_protocol_phase_mid_widget()
        self._mid_stacked_layout.addWidget(self._mid_protocol_phase_widget)

        end_stacked_widget = QWidget()
        end_stacked_widget.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)

        self._end_stacked_layout = QStackedLayout(end_stacked_widget)
        self._end_stacked_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        main_layout.addWidget(end_stacked_widget)

        self._end_widget_manual = self._create_end_widget_manual()
        self._end_stacked_layout.addWidget(self._end_widget_manual)

        self._end_protocol_phase_widget = self._create_protocol_phase_end_widget()
        self._end_stacked_layout.addWidget(self._end_protocol_phase_widget)

        # Optional fourth row - diagnostics
        self._diagnostics_content = DiagnosticsContent(self._app_model)
        main_layout.addWidget(self._diagnostics_content)

        self._frame_count = 0
        self._start = 0

        self._is_diagnostics_visible = True
        self.set_diagnostics_visible(False)

        self._prev_parts_3d_loc = {}
        self._next_parts_3d_loc_report = time.perf_counter()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update_image)
        self._timer.start(int(1000 / self._app_model.preferences.live_feed_refresh_rate))

        # finally, register handlers to events:
        app_model.property_changed += self._model_property_changed
        #
        inference = app_model.inference
        inference.pose_response_ready += self.refresh_pose
        #
        app_model.behavior.algorithm.property_changed += self._behavior_algo_property_changed
        self.training_mode_changed.connect(self._update_training_mode)

    def _create_top_widget_manual(self):
        widget = QWidget()
        widget.setContentsMargins(4, 4, 4, 4)
        top_layout = QHBoxLayout(widget)
        top_layout.setContentsMargins(4, 4, 4, 4)
        top_layout.setSpacing(16)  # given only 3 cam widgets not very large
        top_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # allow auto set of spacing between cameras
        top_layout.addStretch(1)

        self._left_camera_content = CameraContent(self._app_model.left_camera)
        self._left_camera_content.camera_view.setTitle("Left Camera")
        # self._left_camera_content.camera_view.setSize(450, 300)
        top_layout.addWidget(self._left_camera_content)
        self._content_widgets.append(self._left_camera_content)

        top_layout.addStretch(1)

        self._right_camera_content = CameraContent(self._app_model.right_camera)
        self._right_camera_content.camera_view.setTitle("Right Camera")
        # self._right_camera_content.camera_view.setSize(450, 300)
        # self._layout.addWidget(self._right_camera_content, 0, 2, 1, 2)
        top_layout.addWidget(self._right_camera_content)
        self._content_widgets.append(self._right_camera_content)

        top_layout.addStretch(1)

        self._top_camera_content = CameraContent(self._app_model.top_camera)
        self._top_camera_content.camera_view.setTitle("Top Camera")
        # self._top_camera_content.camera_view.setSize(450, 300)
        # self._layout.addWidget(self._top_camera_content, 0, 4, 1, 2)
        top_layout.addWidget(self._top_camera_content)
        self._content_widgets.append(self._top_camera_content)

        top_layout.addStretch(1)

        return widget

    def _create_mid_widget_manual(self, app_model):
        widget = QWidget()
        widget.setContentsMargins(4, 0, 4, 0)

        mid_layout = QHBoxLayout(widget)
        mid_layout.setContentsMargins(4, 4, 4, 4)
        mid_layout.setSpacing(8)

        behavior_content = BehaviorContent(
            app_model,
            app_model.behavior,
            app_model.inference,
        )
        mid_layout.addWidget(behavior_content)
        self._content_widgets.append(behavior_content)

        self._analysis_content = AnalysisContent(
            app_model.hardware,
            app_model.inference,
            app_model.analysis,
            app_model.message_handler,
            app_model.preferences,
        )
        mid_layout.addWidget(self._analysis_content, 3)
        self._content_widgets.append(self._analysis_content)

        return widget

    def _create_end_widget_manual(self):
        # Third row - hardware & alarms
        widget = QWidget()
        widget.setContentsMargins(4, 4, 4, 4)

        end_layout = QHBoxLayout(widget)
        end_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        end_layout.setContentsMargins(0, 0, 0, 0)
        end_layout.setSpacing(8)

        self._hardware_control_content = HardwareControlContent(self._app_model.hardware)
        end_layout.addWidget(self._hardware_control_content)
        self._content_widgets.append(self._hardware_control_content)

        hardware_status_content = HardwareStatusContent(self._app_model.message_handler)
        end_layout.addWidget(hardware_status_content)
        self._content_widgets.append(hardware_status_content)

        alarm_content = self._alarm_content = AlarmContent(self._app_model, self._app_model.hardware)
        alarm_content.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        end_layout.addWidget(alarm_content)
        self._alarm_content_manual_layout = end_layout

        return widget

    def _create_protocol_phase_mid_widget(self):
        widget = QWidget()
        widget.setContentsMargins(4, 4, 4, 4)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        card = CardWidget(title="Protocol")
        layout.addWidget(card)

        card = CardWidget(title="Phase")
        layout.addWidget(card)

        return widget

    def _create_protocol_phase_end_widget(self):
        widget = QWidget()
        widget.setContentsMargins(4, 4, 4, 4)

        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        card = CardWidget(title="Protocol Progress")
        layout.addWidget(card)

        right_layout = QHBoxLayout()
        layout.addLayout(right_layout)

        card = CardWidget(title="Phase Progress")
        right_layout.addWidget(card)

        self._protocol_progress_alarm_content_layout = right_layout

        return widget

    def _update_training_mode(self, training_mode: TrainingMode):
        alarm_content = self._alarm_content
        # remove from both, given if not present then it's identical to no-op,
        self._protocol_progress_alarm_content_layout.removeWidget(alarm_content)
        self._alarm_content_manual_layout.removeWidget(alarm_content)
        # and will add it back where needed:
        if training_mode == TrainingMode.MANUAL:
            self._alarm_content_manual_layout.addWidget(alarm_content)
            self._mid_stacked_layout.setCurrentWidget(self._mid_widget_manual)
            self._end_stacked_layout.setCurrentWidget(self._end_widget_manual)
        else:
            self._protocol_progress_alarm_content_layout.addWidget(alarm_content)
            self._mid_stacked_layout.setCurrentWidget(self._mid_protocol_phase_widget)
            self._end_stacked_layout.setCurrentWidget(self._end_protocol_phase_widget)

    def close(self):
         self._diagnostics_content.close()  # to ensure the textbox handler is remove from root logger handlers
         super().close()

    @Slot()
    def update_image(self):
        model = self._app_model
        if model.left_camera.is_enabled:
            self._left_camera_content.update_image()
        if model.right_camera.is_enabled:
            self._right_camera_content.update_image()
        if model.top_camera.is_enabled:
            self._top_camera_content.update_image()
        self._analysis_content.use_cache()

    def refresh_pose(self, response: PoseResponse):
        if self._app_model.left_camera.is_enabled:
            self._left_camera_content.refresh_pose(response.locations[0])
        if self._app_model.right_camera.is_enabled:
            self._right_camera_content.refresh_pose(response.locations[1])
        if __debug__:
            perf_now = time.perf_counter()
            if perf_now >= self._next_parts_3d_loc_report:
                self._next_parts_3d_loc_report = perf_now + 0.5
                for part, loc_3d in response.locations_3d.items():
                    if response.is_part_seen(part):
                        prev = self._prev_parts_3d_loc.get(part)
                        if prev is None or any(
                            abs(prev[i] - loc_3d[i]) >= 0.15
                            for i in range(3)
                        ):
                            logger.spam("%s: loc3d: %s", part, loc_3d.humanize())
                            self._prev_parts_3d_loc[part] = loc_3d if prev is None else (prev + loc_3d) / 2

    @property
    def is_diagnostics_visible(self) -> bool:
        return self._is_diagnostics_visible

    def set_is_editable(self, is_editable: bool):
        for widget in self._content_widgets:
            widget.set_is_editable(is_editable)

    def set_is_capture_active(self, is_active: bool):
        for widget in self._content_widgets:
            widget.set_is_capture_active(is_active)

    def on_activated(self):
        self._app_model.on_activated()

        self._app_model.left_camera.set_display_fcn(self._left_camera_content.refresh_image)
        self._app_model.right_camera.set_display_fcn(self._right_camera_content.refresh_image)
        self._app_model.top_camera.set_display_fcn(self._top_camera_content.refresh_image)

        for widget in self._content_widgets:
            widget.on_activated()

    def set_diagnostics_visible(self, is_visible: bool):
        self._diagnostics_content.setVisible(is_visible)
        self._is_diagnostics_visible = is_visible
        # if is_visible:
        #     self._layout.setRowStretch(1, 0)
        #     self._layout.setRowStretch(4, 1)
        # else:
        #     self._layout.setRowStretch(1, 1)
        #     self._layout.setRowStretch(4, 0)

    def _model_property_changed(self, name: str, value, _):
        if name == "selected_animal" and value is not None:
            self._hardware_control_content.set_selected_animal(value)

    def _behavior_algo_property_changed(self, name, value, _):
        if name == BehaviorAlgoProps.TRAINING_MODE:
            self.training_mode_changed.emit(value)
