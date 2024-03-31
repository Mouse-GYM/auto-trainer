import time

import numpy

from . camera_base import CameraBase


class RandomCam(CameraBase):
    def __init__(self):
        super().__init__()
        self._rng = numpy.random.default_rng()
        self._last_capture = time.perf_counter()
        self._frame_interval = 1/30.0

    def prepare_capture(self) -> None:
        self._frame_interval = 1 / self._fps

    def capture(self) -> numpy.ndarray:
        now = time.perf_counter()
        delta = now - self._last_capture

        if delta < self._frame_interval:
            time.sleep(self._frame_interval - delta)

        self._last_capture = now

        return self._rng.integers(low=0, high=255, size=(self._height, self._width), dtype="uint8")
