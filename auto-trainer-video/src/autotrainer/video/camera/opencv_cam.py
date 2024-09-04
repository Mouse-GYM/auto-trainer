import logging
import time

import cv2
import numpy

from .camera_base import CameraBase

logger = logging.getLogger(__name__)


class OpenCVCam(CameraBase):
    def __init__(self, device_idx: int, name: str = ""):
        super().__init__(name)
        self._device_idx = device_idx
        self._video_capture = None

    def init(self):
        self._video_capture = cv2.VideoCapture(self._device_idx)

        self._width = int(self._video_capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        self._height = int(self._video_capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self._fps = self._video_capture.get(cv2.CAP_PROP_FPS)

    @property
    def fps(self) -> float:
        return self._fps

    @fps.setter
    def fps(self, value: float) -> None:
        self._video_capture.set(cv2.CAP_PROP_FPS, value)
        self._fps = int(self._video_capture.get(cv2.CAP_PROP_FPS))
        logger.debug(f"<{self._name}> fps: {self._fps}")

    @property
    def width(self):
        return self._width

    @width.setter
    def width(self, value):
        self._video_capture.set(cv2.CAP_PROP_FRAME_WIDTH, value)
        self._refresh_height_width()
        logger.debug(f"<{self._name}> try setting width to {value} - response: ({self._width}x{self._height})")

    @property
    def height(self):
        return self._height

    @height.setter
    def height(self, value):
        self._video_capture.set(cv2.CAP_PROP_FRAME_HEIGHT, value)
        self._refresh_height_width()
        logger.debug(f"<{self._name}> try setting height to {value} - response: ({self._width}x{self._height})")

    def set_property(self, name: str, value: str) -> bool:
        if name == "mjpeg":
            if self._video_capture is not None:
                self._video_capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M', 'J', 'P', 'G'))
        else:
            return super().set_property(name, value)

        return True

    def prepare_capture(self):
        super().prepare_capture()

    def end_capture(self):
        super().end_capture()

        self._video_capture.release()

    def capture(self) -> (numpy.ndarray, int):
        super().capture()

        ret, frame = self._video_capture.read()

        if ret:
            self._last_when = time.time_ns()

        return frame, self._last_when

    def _refresh_height_width(self):
        self._width = int(self._video_capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        self._height = int(self._video_capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
