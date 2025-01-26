import logging
import math
import time
from queue import Queue, Empty
from enum import IntEnum
from threading import Thread
from typing import Callable

from .device_interface import DeviceInterface
from .device import Device
from .device_api import DeviceApi

logger = logging.getLogger(__name__)


# Thread message kind should be negative. Specific devices can use any positive value.
class DeviceThreadMessageKind(IntEnum):
    TERMINATE = -1001,
    CONNECT = -1002,
    DISCONNECT = -1003


class DeviceThread(Thread):
    """ Convenience class to merges a device, device interface, and queues for a client to control the device.

    This class defines a Thread for managing communication between a device and a client script or application.

    The Device is responsible for interpreting data from the device to message the client and interpreting
    messages from the client to send data to the device.

    The DeviceInterface is responsible for low-level communication with the device over a specific protocol.

    Optional command and message queues are interfaces for the client script or application to exchange data with
    the device.

    """

    def __init__(self, device: Device, interface: DeviceInterface, message_queue: Queue = None,
                 message_callback: Callable[[int, object], None] = None):
        super().__init__()

        self._device = device
        self._interface = interface
        self._message_callback = message_callback
        self._message_queue = message_queue
        self._cmd_queue: Queue = Queue()

        self._api = DeviceApi(self._interface, message_callback=message_callback, message_queue=message_queue)
        self._device.api = self._api

        self._name = "device-thread"

        self._read_limit: int = math.inf

    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, value: str):
        self._name = value

    @property
    def read_limit(self) -> int:
        return self._read_limit

    @read_limit.setter
    def read_limit(self, value: int):
        self._read_limit = value

    def send_message(self, kind: int, data: object = None, context: object = None):
        if self._cmd_queue is not None:
            self._cmd_queue.put_nowait((kind, data, context))

    def run(self) -> None:
        logger.debug(f"<{self._name}> thread started")

        while True:
            if not self._run_unconnected():
                break

            if not self._run_connected():
                break

        logger.debug(f"<{self._name}> thread terminated")

    def _run_unconnected(self) -> bool:
        while True:
            try:
                cmd, data, context = self._cmd_queue.get_nowait()

                if cmd == DeviceThreadMessageKind.TERMINATE:
                    logger.debug(f"<{self._name}> message: {DeviceThreadMessageKind(cmd).name}")
                    return False
                elif cmd == DeviceThreadMessageKind.CONNECT:
                    logger.debug(f"<{self._name}> message: {DeviceThreadMessageKind(cmd).name}")
                    break
                else:
                    logger.debug(f"<{self._name}> message: {cmd} ignored")
            except Empty:
                time.sleep(0.0001)

        if not self._interface.is_open:
            try:
                success = self._interface.open()

                if success:
                    logger.debug(f"<{self._name}> interface open")
                    self._device.connect()
                    logger.debug(f"<{self._name}> device connected")
                else:
                    logger.warning(f"<{self._name}> failed to open device")
                    return False
            except Exception as ex:
                logger.error(f"<{self._name}> {ex}")
                return False
        else:
            logger.warning(f"<{self._name}>CONNECT cmd while device already open")

        return True

    def _run_connected(self) -> bool:
        while True:
            # Data from the device for the device listener to process.
            heartbeat = 0
            while self._interface.can_read():
                self._device.notify_data(self._interface.read(self._read_limit))
                heartbeat += 1
                if heartbeat > 5:
                    break

            # Messages from the client of this class to control the device listener (or this class, such as TERMINATE).
            try:
                cmd, data, context = self._cmd_queue.get_nowait()

                if cmd == DeviceThreadMessageKind.TERMINATE:
                    logger.debug(f"<{self._name}> message: {DeviceThreadMessageKind(cmd).name}")
                    return False
                elif cmd == DeviceThreadMessageKind.DISCONNECT:
                    logger.debug(f"<{self._name}> message: {DeviceThreadMessageKind(cmd).name}")
                    break
                else:
                    self._device.notify_message(cmd, data, context)
            except Empty:
                time.sleep(0.0001)

        if self._interface.is_open:
            self._device.disconnect()

            self._interface.close()

            logger.debug(f"<{self._name}> interface closed")
        else:
            logger.warning(f"<{self._name} DISCONNECT cmd while device already disconnected")

        return True
