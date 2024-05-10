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
    TERMINATE = -1,
    COMMAND_ACK = -2


class DeviceThread(Thread):
    """ Convenience class to merges a device listener, device interface, and queues for a client to control the device.

    This class defines a Thread for managing communication between a device and a client script or application.

    The device listener is responsible for interpreting data from the device to message the client and interpreting
    messages from the client to send data to the device.

    The device interface is responsible for low-level communication with the device over a specific protocol.

    Command and message queues are the interfaces for the client script or application to exchange data with the device.

    """
    def __init__(self, listener: IDeviceListener, interface: IDeviceInterface, cmd_queue=None, msg_queue=None):
        super().__init__()

        self._listener = listener
        self._interface = interface
        self._cmd_queue = cmd_queue
        self._msg_queue = msg_queue

        self._api = DeviceApi(self._interface, self.send_message)
        self._listener.api = self._api

    def send_message(self, kind: int, context: object):
        # Messages from the device listener to the client
        if self._msg_queue is not None:
            self._msg_queue.put((kind, context))

    def run(self) -> None:
        self._interface.open()

        logger.debug("interface open")

        self._listener.connect()

        while True:
            # Data from the device for the device listener to process.
            while self._interface.can_read():
                self._listener.notify_data(self._interface.read())

            # Messages from the client of this class to control the device listener (or this class, such as TERMINATE).
            try:
                cmd, data, context = self._cmd_queue.get(False)

                logger.debug(f"message: {cmd}")

                if cmd == DeviceThreadMessageKind.TERMINATE:
                    break

                self._listener.notify_message(cmd, data, context)
            except queue.Empty:
                pass

            time.sleep(0.001)

        self._listener.disconnect()

        self._interface.close()

        logger.debug("interface closed")
