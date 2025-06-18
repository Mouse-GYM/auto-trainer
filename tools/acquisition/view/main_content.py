import typing
from typing import Tuple

from PySide6 import QtCore
from PySide6.QtCore import QTimer, Slot
from PySide6.QtWidgets import QGridLayout

from autotrainer.core import Offset3DTuple
from autotrainer.core.logging import get_verbose_logger
from autotrainer.inference import PoseResponse, PoseAlgorithm
from autotrainer.pyside import ATSeparator

from tools.acquisition.model.app_model import AppModel
from tools.acquisition.view.analysis_content import AnalysisContent
from tools.acquisition.view.content_widget import ContentWidget
from tools.acquisition.view.behavior_content import BehaviorContent
from tools.acquisition.view.camera_content import CameraContent
from tools.acquisition.view.diagnostics_content import DiagnosticsContent
from tools.acquisition.view.hardware_control_content import HardwareControlContent
from tools.acquisition.view.hardware_status_content import HardwareStatusContent


logger = get_verbose_logger(__name__)


class MainContent(ContentWidget):
    def __init__(self, model: AppModel):
        super().__init__()

        self._model = model

        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("MainContent")
        self.setStyleSheet("#MainContent {background-color: #f7f7f7}")

        self._content_widgets: typing.List[ContentWidget] = list()

        self.setContentsMargins(0, 0, 0, 0)

        self._layout = QGridLayout()
        self._layout.setHorizontalSpacing(0)
        self._layout.setVerticalSpacing(0)
        self._layout.setSpacing(0)
        self._layout.setContentsMargins(0, 0, 0, 0)

        # self._layout.setColumnStretch(7, 1)

        # First rows - cameras

        self._left_camera_content = CameraContent(self._model.left_camera)
        self._left_camera_content.camera_view.setTitle("Left Camera")
        # self._left_camera_content.camera_view.setSize(450, 300)

        self._layout.addWidget(self._left_camera_content, 0, 0, 1, 2)
        self._content_widgets.append(self._left_camera_content)

        self._right_camera_content = CameraContent(self._model.right_camera)
        self._right_camera_content.camera_view.setTitle("Right Camera")
        # self._right_camera_content.camera_view.setSize(450, 300)

        self._layout.addWidget(self._right_camera_content, 0, 2, 1, 2)
        self._content_widgets.append(self._right_camera_content)

        self._top_camera_content = CameraContent(self._model.top_camera)
        self._top_camera_content.camera_view.setTitle("Top Camera")
        # self._top_camera_content.camera_view.setSize(450, 300)

        self._layout.addWidget(self._top_camera_content, 0, 4, 1, 2)
        self._content_widgets.append(self._top_camera_content)

        # Second row - behavior and analysis

        behavior_content = BehaviorContent(self._model.behavior, self._model.inference)
        self._layout.addWidget(behavior_content, 1, 0, 1, 3)
        self._content_widgets.append(behavior_content)

        self._analysis_content = AnalysisContent(self._model.hardware, self._model.inference, self._model.analysis,
                                                 self._model.message_handler)
        self._layout.addWidget(self._analysis_content, 1, 3, 1, 3)
        self._content_widgets.append(self._analysis_content)

        # Third row - hardware

        self._hardware_control_content = HardwareControlContent(self._model.hardware)
        self._layout.addWidget(self._hardware_control_content, 2, 0, 1, 3)
        self._content_widgets.append(self._hardware_control_content)

        hardware_status_content = HardwareStatusContent(self._model.message_handler)
        self._layout.addWidget(hardware_status_content, 2, 3, 1, 3)
        self._content_widgets.append(hardware_status_content)

        # Optional fourth row - diagnostics

        self._diagnostics = DiagnosticsContent(self._model)
        self._layout.addWidget(self._diagnostics, 4, 0, 1, 6)

        self._layout.setRowStretch(1, 1)

        self._layout.addWidget(ATSeparator("#b9b9b9"), 5, 0, 1, 8)

        self.setLayout(self._layout)

        self._is_diagnostics_visible = True

        self._frame_count = 0

        self._start = 0

        # register handlers to events:
        self._model.property_changed += self._model_property_changed
        inference = self._model.inference
        inference.pose_response_ready += self.refresh_pose

        self.set_diagnostics_visible(False)

        self._prev_top_cam_detect = None

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update_image)
        self._timer.start(int(1000 / self._model.preferences.live_feed_refresh_rate))


    @Slot()
    def update_image(self):
        model = self._model
        top_cam_pres = model.top_camera_presence_detection
        cur_val = top_cam_pres.presence_detected.value
        if cur_val != self._prev_top_cam_detect:
            cur_sum = top_cam_pres.pc_sum.value
            logger.notice("top_camera presence detected: %s sum=%s", cur_val, cur_sum)
            self._prev_top_cam_detect = cur_val
        if model.left_camera.is_enabled:
            self._left_camera_content.update_image()
        if model.right_camera.is_enabled:
            self._right_camera_content.update_image()
        if model.top_camera.is_enabled:
            self._top_camera_content.update_image()
        self._analysis_content.use_cache()

    def refresh_pose(self, response: PoseResponse):
        if self._model.left_camera.is_enabled:
            self._left_camera_content.refresh_pose(response.locations[0])
        if self._model.right_camera.is_enabled:
            self._right_camera_content.refresh_pose(response.locations[1])

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
        self._model.on_activated()

        self._model.left_camera.set_display_fcn(self._left_camera_content.refresh_image)
        self._model.right_camera.set_display_fcn(self._right_camera_content.refresh_image)
        self._model.top_camera.set_display_fcn(self._top_camera_content.refresh_image)

        for widget in self._content_widgets:
            widget.on_activated()

    def set_diagnostics_visible(self, is_visible: bool):
        self._diagnostics.setVisible(is_visible)
        self._is_diagnostics_visible = is_visible
        if is_visible:
            self._layout.setRowStretch(1, 0)
            self._layout.setRowStretch(4, 1)
        else:
            self._layout.setRowStretch(1, 1)
            self._layout.setRowStretch(4, 0)

    def _model_property_changed(self, name: str, value, old_value):
        if name == "selected_animal" and value is not None:
            self._hardware_control_content.set_selected_animal(value)
