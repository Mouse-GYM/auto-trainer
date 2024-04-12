import time
import urllib.parse

import cv2
import numpy

from . camera_base import CameraBase


class PlaybackCam(CameraBase):
    def __init__(self, file_name, name: str = ""):
        super().__init__(name)
        self._file_name = file_name
        self._file_name = urllib.parse.unquote(file_name)
        self._frame_interval = 1 / 30
        self._video_capture = None

    def init(self):
        self._video_capture = cv2.VideoCapture(self._file_name)
        self.fps = self._video_capture.get(cv2.CAP_PROP_FPS)
        self._frame_interval = 1 / self.fps
        self.width = self._video_capture.get(cv2.CAP_PROP_FRAME_WIDTH)
        self.height = self._video_capture.get(cv2.CAP_PROP_FRAME_HEIGHT)

    def capture(self) -> (numpy.ndarray, int):
        now = time.perf_counter_ns()

        delta = 1e-9 * (now - self._last_when)

        if delta < self._frame_interval:
            time.sleep(self._frame_interval - delta)
            
        super().capture()

        self._last_when = time.perf_counter_ns()

        ret, frame = self._video_capture.read()

        return frame[:, :, 1], self._last_when
