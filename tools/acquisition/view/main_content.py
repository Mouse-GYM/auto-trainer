import logging
import os
import pathlib

from PySide6.QtWidgets import QWidget, QGridLayout, QPlainTextEdit

from autotrainer.ATSeparator import ATSeparator
from autotrainer.TextBoxHandler import TextBoxHandler

from tools.acquisition.model.app_model import AppModel
from tools.acquisition.model.camera_model import CameraModel
from tools.acquisition.view.analysis_content import AnalysisContent
from tools.acquisition.view.camera_content import CameraContent
from tools.acquisition.view.pellet_delivery_content import PelletDeliveryContent
from tools.acquisition.view.head_fix_content import HeadFixContent
from tools.acquisition.view.output_content import OutputContent


def create_camera_list():
    cameras = list()

    cameras.append(CameraModel("Random Image", "random://0?width=300&height=200"))

    loc = pathlib.Path(__file__).parent.resolve().parents[2].joinpath("cameras.txt")

    if os.path.isfile(loc):
        file = open(loc, "r")
        lines = file.readlines()
        file.close()
        for line in lines:
            parts = line.split(",")
            if len(parts) == 2:
                cameras.append(CameraModel(parts[0].strip(), parts[1].strip()))

    return cameras


class MainContent(QWidget):
    def __init__(self, app_view_model: AppModel):
        super().__init__()

        self._app_view_model = app_view_model

        self._camera_list = create_camera_list()

        layout = QGridLayout()

        layout.setColumnStretch(3, 1)

        self._left_camera_content = CameraContent(self._app_view_model.left_camera, self._camera_list)
        self._left_camera_content.camera_view.setTitle("Left Camera")
        self._left_camera_content.camera_view.set_size(450, 300)

        layout.addLayout(self._left_camera_content, 0, 0)

        self._right_camera_content = CameraContent(self._app_view_model.right_camera, self._camera_list)
        self._right_camera_content.camera_view.setTitle("Right Camera")
        self._right_camera_content.camera_view.set_size(450, 300)

        layout.addLayout(self._right_camera_content, 0, 1)

        self._top_camera_content = CameraContent(self._app_view_model.top_camera, self._camera_list)
        self._top_camera_content.camera_view.setTitle("Top Camera")
        self._top_camera_content.camera_view.set_size(450, 300)

        layout.addLayout(self._top_camera_content, 0, 2)

        layout.addWidget(ATSeparator("#b9b9b9"), 1, 0, 1, 4)

        self._head_fix_content = HeadFixContent(self._app_view_model.head_fix)
        layout.addLayout(self._head_fix_content, 2, 0, 1, 4)

        layout.addWidget(ATSeparator("#b9b9b9"), 3, 0, 1, 4)

        self._pellet_delivery_content = PelletDeliveryContent(self._app_view_model.pellet_delivery)
        layout.addWidget(self._pellet_delivery_content, 4, 0, 1, 4)

        layout.addWidget(ATSeparator("#b9b9b9"), 5, 0, 1, 4)

        # layout.addLayout(AnalysisContent(), 6, 0, 1, 4)

        # layout.addWidget(ATSeparator("#b9b9b9"), 7, 0, 1, 4)

        layout.addLayout(OutputContent(app_view_model.user_settings), 8, 0, 1, 4)

        layout.addWidget(ATSeparator("#b9b9b9"), 9, 0, 1, 4)

        log_output = QPlainTextEdit()
        log_output.setReadOnly(True)
        log_output.setStyleSheet("border: 1px solid; border-color: #b9b9b9;")
        handler = TextBoxHandler(log_output)
        handler.setFormatter(logging.Formatter(fmt="%(asctime)s: %(levelname)s: %(name)s: %(message)s"))
        logging.getLogger().addHandler(handler)

        log_layout = QGridLayout()
        log_layout.setContentsMargins(8, 8, 8, 8)
        log_layout.addWidget(log_output)

        layout.addLayout(log_layout, 10, 0, 1, 4)

        layout.setRowStretch(10, 1)

        layout.addWidget(ATSeparator("#b9b9b9"), 11, 0, 1, 4)

        self.setLayout(layout)

        self._frame_count = 0

        self._start = 0

    def setCaptureEnabled(self, enabled: bool):
        self._left_camera_content.setCaptureEnabled(enabled)
        self._right_camera_content.setCaptureEnabled(enabled)
        self._top_camera_content.setCaptureEnabled(enabled)
        self._head_fix_content.setCaptureEnabled(enabled)
        self._pellet_delivery_content.setCaptureEnabled(enabled)

    def on_activated(self):
        self._app_view_model.left_camera.set_display_fcn(self._left_camera_content.refresh_image)
        self._app_view_model.right_camera.set_display_fcn(self._right_camera_content.refresh_image)
        self._app_view_model.top_camera.set_display_fcn(self._top_camera_content.refresh_image)
