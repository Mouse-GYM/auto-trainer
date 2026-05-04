import logging
import math
import time
from typing import Tuple, Optional

import cv2
import numpy

from .camera_base import CameraBase

logger = logging.getLogger(__name__)


class OpenCVCam(CameraBase):

    def __init__(self, device_idx: int, name: str = ""):
        super().__init__(name)
        self._device_idx = device_idx
        self._video_capture: Optional[cv2.VideoCapture] = None
        self._mjpeg = None
        self._prev_frame_perf_now = -math.inf
        self._frame_half_period = math.nan

    def init(self):
        vc = self._video_capture = cv2.VideoCapture()
        if not vc.open(self._device_idx) and vc.isOpened():
            raise RuntimeError(f"Could not connect to video capture device {self._device_idx}")
        self._apply_settings()
        # re-read:
        self._refresh_height_width()
        requested_fps = self._fps
        self._fps = self._video_capture.get(cv2.CAP_PROP_FPS)
        logger.info("requested fps=%s ; obtained fps=%s", requested_fps, self._fps)
        self._frame_half_period = 0.5 / self._fps

    def _apply_settings(self):
        vc = self._video_capture
        vc.set(cv2.CAP_PROP_FPS, self._fps)
        vc.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        vc.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        mjpeg = self._mjpeg
        if mjpeg is not None:
            vc.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M', 'J', 'P', 'G'))

    @property
    def fps(self) -> float:
        return self._fps

    @fps.setter
    def fps(self, value: float) -> None:
        self._fps = value

    @property
    def width(self):
        return self._width

    @width.setter
    def width(self, value):
        self._width = value

    @property
    def height(self):
        return self._height

    @height.setter
    def height(self, value):
        self._height = value

    def set_property(self, name: str, value: str) -> bool:
        if name == "mjpeg":
            self._mjpeg = value
        else:
            return super().set_property(name, value)

        return True

    def prepare_capture(self):
        super().prepare_capture()

    def end_capture(self):
        super().end_capture()
        self._video_capture.release()

    def capture(self) -> Tuple[numpy.ndarray, int]:
        prev_frame_id = self._last_frame_id
        super().capture()
        vc = self._video_capture
        if vc is None:
            raise RuntimeError("video_capture not open")
        ret, frame = vc.read()
        if not ret:
            raise RuntimeError(f"failed read frame {prev_frame_id + 1} on {vc}")
        perf_now = time.perf_counter()
        if prev_frame_id > -1:  # not first frame
            estimated_drop = int((perf_now - self._prev_frame_perf_now - self._frame_half_period) * self._fps)
            if estimated_drop > 0:
                self._last_frame_id += estimated_drop
                logger.debug("corrected frame_id to %s due to estimated_drop=%s", self._last_frame_id, estimated_drop)
        self._prev_frame_perf_now = perf_now
        return frame, self._last_when

    def _refresh_height_width(self):
        self._width = int(self._video_capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        self._height = int(self._video_capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
