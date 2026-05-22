import logging
import math
import time
from typing import Tuple, Optional

import cv2
import numpy

from autotrainer.core.logging import get_verbose_logger

from .camera_base import CameraBase

logger = get_verbose_logger(__name__)


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
        if not vc.open(self._device_idx) or not vc.isOpened():
            raise RuntimeError(f"Could not connect to video capture device {self._device_idx}")
        self._apply_settings(vc)
        # re-read:
        self._width = int(vc.get(cv2.CAP_PROP_FRAME_WIDTH))
        self._height = int(vc.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if not (self._width > 0 and self._height > 0):
            vc.release()
            self._video_capture = None
            raise RuntimeError(f"width or height non-positive: ({self._width}, {self._height})")
        requested_fps = self._fps
        fps = self._fps = vc.get(cv2.CAP_PROP_FPS)
        logger.info("requested fps=%s ; obtained fps=%s", requested_fps, fps)
        if fps <= 0:
            vc.release()
            self._video_capture = None
            raise RuntimeError("read fps from camera negative or zero")
        self._frame_half_period = 0.5 / self._fps

    def _apply_settings(self, vc: cv2.VideoCapture):
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
            diff_prev = perf_now - self._prev_frame_perf_now
            estimated_drop = int((diff_prev - self._frame_half_period) * self._fps)
            if estimated_drop > 0:
                self._last_frame_id += estimated_drop
                # current topcam process apparently cannot keep aligned with the current FPS very often,
                # so only log with more than 1 frame drop:
                if estimated_drop > 1:
                    logger.verbose(  # keeping as verbose instead of warning for now
                        "corrected frame_id to %s due to estimated_drop=%s. diff=%.4f prev_frame_perf=%.3f frame_perf=%.3f",
                        self._last_frame_id, estimated_drop, diff_prev, self._prev_frame_perf_now, perf_now)
        self._prev_frame_perf_now = perf_now
        return frame, self._last_when
