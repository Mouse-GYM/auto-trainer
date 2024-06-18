import logging
import time
from queue import Queue
from threading import Thread
from typing import Callable

from . import GymDeviceMessageKind
from .device_thread import DeviceThreadMessageKind

logger = logging.getLogger(__name__)


class PelletReader(Thread):
    def __init__(self, input_queue: Queue, ack_callback: Callable[[object], None] = None,
                 version_callback: Callable[[str], None] = None):
        super().__init__()

        self._input_queue = input_queue
        self._ack_callback = ack_callback
        self._version_callback = version_callback

    @property
    def version_callback(self):
        return self._version_callback

    @version_callback.setter
    def version_callback(self, version_callback: Callable[[str], None]):
        self._version_callback = version_callback

    @property
    def ack_callback(self):
        return self._ack_callback

    @ack_callback.setter
    def ack_callback(self, ack_callback:  Callable[[object], None]):
        self._ack_callback = ack_callback

    def run(self):
        logger.debug("entering PelletReader")

        while True:
            msg, data = self._input_queue.get()

            if msg == DeviceThreadMessageKind.TERMINATE:
                break
            elif msg == GymDeviceMessageKind.ACK:
                if self._ack_callback is not None:
                    self._ack_callback(data)
            elif msg == GymDeviceMessageKind.VERSION:
                if self._version_callback is not None:
                    self._version_callback(data)

            time.sleep(0.0001)

        logger.debug("exiting PelletReader")
