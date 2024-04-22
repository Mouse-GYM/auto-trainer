import logging
import queue
import time
from enum import IntEnum
from threading import Thread

from .device_interface import IDeviceInterface
from .device_listener import IDeviceListener
from .device_api import DeviceApi

logger = logging.getLogger(__name__)


# Thread message kind should be negative. Specific devices can use any positive value.
class DeviceThreadMessageKind(IntEnum):
    TERMINATE = -1


class DeviceThread(Thread):
    def __init__(self, listener: IDeviceListener, interface: IDeviceInterface, cmd_queue=None, msg_queue=None):
        super().__init__()

        self._listener = listener
        self._interface = interface
        self._cmd_queue = cmd_queue
        self._msg_queue = msg_queue

        self._api = DeviceApi(self._interface, self.send_message)
        self._listener.api = self._api

    def send_message(self, kind: int, context: object):
        if self._msg_queue is not None:
            self._msg_queue.put((kind, context))

    def run(self) -> None:
        self._interface.open()

        logger.debug("interface open")

        self._listener.connect()

        while True:
            while self._interface.can_read():
                self._listener.notify_data(self._interface.read())

            try:
                msg = self._cmd_queue.get(False)

                logger.debug(f"message: {msg[0]}")

                if msg[0] == DeviceThreadMessageKind.TERMINATE:
                    break

                self._listener.notify_message(msg[0], msg[1])
            except queue.Empty:
                pass

            time.sleep(0.001)

        self._listener.disconnect()

        self._interface.close()

        logger.debug("interface closed")
