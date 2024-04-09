import queue
import time
import logging

import numpy
from PySide6.QtCore import Signal, QObject

logger = logging.getLogger(__name__)


class VideoReader(QObject):
    """
    Block on an image Queue off of the GUI thread and emit to the GUI thread when an image is available
    """

    image_ready = Signal(numpy.ndarray)

    def __init__(self, image_queue : queue.Queue, decimation: int = 10):
        super().__init__()
        self._image_queue = image_queue
        self._decimation = decimation

    @property
    def decimation(self) -> int:
        return self._decimation
    
    @decimation.setter
    def decimation(self, value: int)-> None:
        self._decimation = max(1, value)

    def process(self):
        count = 0
        acq_start = 0

        while True:
            try:
                data = self._image_queue.get_nowait()
                if count == 0:
                    acq_start = time.perf_counter_ns()
                if count % self._decimation == 0:
                    self.image_ready.emit(data)
                count += 1
                # if count % 1000 == 0:    
                #    acq_end = time.perf_counter_ns()
                #    logger.info(f"reader fps: {int(count * 1e9 /(acq_end - acq_start))}")
            except queue.Empty:
                pass

