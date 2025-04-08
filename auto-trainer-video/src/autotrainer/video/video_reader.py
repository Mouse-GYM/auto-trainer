import queue
import time
import logging
from threading import Event, Thread

logger = logging.getLogger(__name__)


class VideoReader(Thread):
    """
    Block on an image Queue off of the GUI thread
    """

    def __init__(self, name: str, image_queue: queue.Queue, update_fcn, stop_event: Event, reset_event: Event = None,
                 decimation: int = 10):
        super().__init__()
        self._image_queue = image_queue
        self._update_fcn = update_fcn
        self._name = name
        self._stop_event = stop_event if stop_event is not None else Event()
        self._reset_event = reset_event if reset_event is not None else Event()
        self._decimation = decimation

    @property
    def decimation(self) -> int:
        return self._decimation

    @decimation.setter
    def decimation(self, value: int) -> None:
        self._decimation = max(1, value)
        if self._decimation != 1:
            logger.debug(f"<{self._name}> decimation set to {self._decimation}")

    def run(self):
        count = 0

        while True:
            if self._stop_event.is_set():
                break

            if self._reset_event.is_set():
                count = 0
                self._reset_event.clear()

            try:
                if self._image_queue is not None:
                    data = self._image_queue.get(block=False, timeout=0.01)
                    if count % self._decimation == 0:
                        self._update_fcn(data)
                    count += 1
                else:
                    # Unclear how universal this is, but the combination of [Jetson, JetPack 5, Ubuntu 20, Python] will
                    # massively slow down the system without explicitly yielding, despite being in its own thread.  This
                    # is not the case for other platforms/combinations of the above so may not be apparent when not on
                    # the current deployment platform.
                    time.sleep(0.001)
            except queue.Empty:
                pass
