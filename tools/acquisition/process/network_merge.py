import logging
import queue

from PySide6.QtCore import QThread

logger = logging.getLogger(__name__)


class NetworkMerge(QThread):
    def __init__(self, input_queue_1, input_queue_2, output_queue):
        super().__init__()

        self._input_queue_1 = input_queue_1
        self._input_queue_2 = input_queue_2
        self._output_queue = output_queue

    def run(self):
        logger.info("NetworkMerge started.")

        while True:
            if self.isInterruptionRequested():
                break

            try:
                image_1 = self._input_queue_1.get(block=False, timeout=0.001)
                image_2 = self._input_queue_2.get(block=False, timeout=0.001)

                self._output_queue.put((image_1, image_2))
            except queue.Empty:
                pass

        while not self._output_queue.empty() or self._output_queue.qsize() > 0:
            try:
                self._output_queue.get_nowait()
            except queue.Empty:
                pass

        logger.info("NetworkMerge ended.")
