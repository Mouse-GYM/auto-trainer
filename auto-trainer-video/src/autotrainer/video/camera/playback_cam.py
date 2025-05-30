import time
import urllib.parse

import cv2
import numpy

from . camera_base import CameraBase
from autotrainer.core.logging import get_verbose_logger

logger = get_verbose_logger(__name__)


class PlaybackCam(CameraBase):
    def __init__(self, file_name, name: str = ""):
        super().__init__(name)
        self._file_name = file_name
        self._file_name = urllib.parse.unquote(file_name)
        self._video_capture = None
        self._make_precise_timestamps = False
        # make_precise_timestamps:
        # used to bypass/workaround analyse code only being able to handle very precise timestamps

    def init(self):
        self._video_capture = cv2.VideoCapture(self._file_name)
        self.fps = self._video_capture.get(cv2.CAP_PROP_FPS)
        if self.fps == 0:
            self.fps = 30
        self.width = self._video_capture.get(cv2.CAP_PROP_FRAME_WIDTH)
        self.height = self._video_capture.get(cv2.CAP_PROP_FRAME_HEIGHT)
        logger.notice("init with fps=%s W=%s H=%s", self.fps, self.width, self.height)

    def capture(self) -> (numpy.ndarray, int):
        ret, frame = self._video_capture.read()
        if not ret:
            raise RuntimeError(f"capture failed on {self._video_capture}")
        max_diff = 0.05 / self._fps
        while True:
            now = time.time_ns()
            delta = self._frame_count / self._fps - 1e-9 * (now - self._capture_start)
            if delta < max_diff:
                break
            time.sleep(0.5 * delta)
        super().capture()
        if self._make_precise_timestamps:
            new_last_when = self._capture_start + self._frame_count * int(1e9 / self._fps)
            self._last_when = new_last_when
        return frame[:, :, 1], self._last_when
