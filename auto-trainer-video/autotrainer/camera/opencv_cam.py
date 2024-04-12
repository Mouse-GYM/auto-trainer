import time

import cv2
import numpy

from . camera_base import CameraBase


class OpenCVCam(CameraBase):
    def __init__(self, device_idx: int, name: str = ""):
        super().__init__(name)
        self._device_idx = device_idx
        self._video_capture = None

    def init(self):
        self._video_capture = cv2.VideoCapture(self._device_idx)

        self.width = int(self._video_capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self._video_capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.fps = self._video_capture.get(cv2.CAP_PROP_FPS)

    def prepare_capture(self):
        super().prepare_capture()

    def end_capture(self):
        super().end_capture()
        
        self._video_capture.release()

    def capture(self) -> (numpy.ndarray, int):
        super().capture()

        ret, frame = self._video_capture.read()

        self._last_when = time.perf_counter_ns()

        frame = frame[:, :, 0]

        return frame, self._last_when
