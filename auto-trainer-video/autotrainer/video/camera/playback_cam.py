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
        self._video_capture = None

    def init(self):
        self._video_capture = cv2.VideoCapture(self._file_name)

        self.fps = self._video_capture.get(cv2.CAP_PROP_FPS)
        if self.fps == 0:
            self.fps = 30

        self.width = self._video_capture.get(cv2.CAP_PROP_FRAME_WIDTH)

        self.height = self._video_capture.get(cv2.CAP_PROP_FRAME_HEIGHT)

    def capture(self) -> (numpy.ndarray, int):
        now = time.perf_counter_ns()

        delta = self._frame_count / self._fps - 1e-9 * (now - self._capture_start)

        if delta > 0:
            time.sleep(delta)
            
        super().capture()

        ret, frame = self._video_capture.read()

        return frame[:, :, 1], self._last_when
