import queue

import numpy
from PySide6.QtCore import Signal, QObject


class VideoReader(QObject):
    """
    Block on an image Queue off of the GUI thread and emit to the GUI thread when an image is available
    """

    image_ready = Signal(numpy.ndarray)

    def __init__(self, image_queue : queue.Queue, decimation: int = 10):
        super().__init__()
        self._image_queue = image_queue
        self._decimation = decimation

    def process(self):
        count = 0
        while True:
            try:
                data = self._image_queue.get(block=False, timeout=0.001)
                if count % self._decimation == 0:
                    self.image_ready.emit(data)
                count += 1
            except queue.Empty:
                pass
