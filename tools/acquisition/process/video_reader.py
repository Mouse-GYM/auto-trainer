import queue
import time
import logging
from threading import Event

import numpy
from PySide6.QtCore import Signal, QObject

logger = logging.getLogger(__name__)


class VideoReader(QObject):
    """
    Block on an image Queue off of the GUI thread and emit to the GUI thread when an image is available
    """

    image_ready = Signal(numpy.ndarray)

    def __init__(self, image_queue: queue.Queue, reset_event: Event = None, decimation: int = 10):
        super().__init__()
        self._image_queue = image_queue
        self._reset_event = reset_event if reset_event is not None else Event()
        self._decimation = decimation

    @property
    def decimation(self) -> int:
        return self._decimation

    @decimation.setter
    def decimation(self, value: int) -> None:
        self._decimation = max(1, value)
        logger.debug(f"decimation set to {self._decimation}")

    def process(self):
        count = 0
        acq_start = 0

        while True:
            if self._reset_event.is_set():
                count = 0
                self._reset_event.clear()
                logger.debug("reader frame count reset")

            try:
                data = self._image_queue.get(block=False, timeout=0.01)
                if count == 0:
                    acq_start = time.perf_counter_ns()
                if count % self._decimation == 0:
                    self.image_ready.emit(data)
                count += 1
                if count % 750 == 0:
                    acq_end = time.perf_counter_ns()
                    logger.debug(f"reader fps: ~{int(count * 1e9 / (acq_end - acq_start))}")
            except queue.Empty:
                pass
