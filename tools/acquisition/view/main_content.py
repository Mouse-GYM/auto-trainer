import typing

from PySide6 import QtCore
from PySide6.QtCore import QTimer, Slot
from PySide6.QtWidgets import QGridLayout, QVBoxLayout

from autotrainer.inference import PoseResponse
from autotrainer.pyside import ATSeparator

from tools.acquisition.model.app_model import AppModel
from tools.acquisition.view.content_widget import ContentWidget
from tools.acquisition.view.behavior_content import BehaviorContent
from tools.acquisition.view.camera_content import CameraContent
from tools.acquisition.view.diagnostics_content import DiagnosticsContent
from tools.acquisition.view.pellet_delivery_content import PelletDeliveryContent
from tools.acquisition.view.head_fix_content import HeadFixContent
from tools.acquisition.view.output_content import OutputContent


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

        self._pellet_delivery_content = PelletDeliveryContent(self._model.pellet_delivery)
        self._layout.addWidget(self._pellet_delivery_content, 3, 0, 1, 3)
        self._content_widgets.append(self._pellet_delivery_content)

        analysis_content = BehaviorContent(self._model.behavior, self._model.analysis)
        self._layout.addWidget(analysis_content, 1, 0, 2, 3)
        self._content_widgets.append(analysis_content)

        self._head_fix_content = HeadFixContent(self._model.head_fix)
        self._layout.addWidget(self._head_fix_content, 1, 3, 2, 3)
        self._content_widgets.append(self._head_fix_content)

        output_content = OutputContent(self._model)
        self._layout.addWidget(output_content, 3, 3, 1, 3)
        self._content_widgets.append(output_content)

        self._diagnostics = DiagnosticsContent(self._model)
        self._layout.addWidget(self._diagnostics, 4, 0, 1, 6)

        self._layout.setRowStretch(4, 1)

        self._layout.addWidget(ATSeparator("#b9b9b9"), 5, 0, 1, 8)

        self.setLayout(self._layout)

        self._is_diagnostics_visible = True

        self._frame_count = 0

        self._start = 0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update_image)
        self._timer.start(int(1000 / self._model.preferences.live_feed_refresh_rate))

        self._model.analysis.pose_response_ready += self.refresh_pose

        self.set_diagnostics_visible(False)

    @Slot()
    def update_image(self):
        if self._model.left_camera.is_enabled:
            self._left_camera_content.update_image()
        if self._model.right_camera.is_enabled:
            self._right_camera_content.update_image()
        if self._model.top_camera.is_enabled:
            self._top_camera_content.update_image()
        self._head_fix_content.use_cache()

    def refresh_pose(self, response: PoseResponse):
        if self._model.left_camera.is_enabled:
            self._left_camera_content.refresh_pose(response.x_y_1())
        if self._model.right_camera.is_enabled:
            self._right_camera_content.refresh_pose(response.x_y_2())

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
