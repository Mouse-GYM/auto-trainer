import logging
import math
import time
from queue import Queue, Empty
from enum import IntEnum
from threading import Thread
from typing import Callable

from autotrainer.core.message import MotorConfigurations

from .device import Device
from .can_device import HAVE_CAN_DEVICE
from .device_api import DeviceApi
from .device_interface import ServoConfig, StepperConfig
from .motor_steps import CompoundMovementDataSet, MotorSteps
from ..core import SystemCommandKind

logger = logging.getLogger(__name__)


# Thread message kind should be negative. Specific devices can use any positive value.
class DeviceThreadMessageKind(IntEnum):
    TERMINATE = -1001,
    CONNECT = -1002,
    DISCONNECT = -1003


_REQUEST_TERMINATE = DeviceThreadMessageKind.TERMINATE


class DeviceConnection:
    """
    Convenience class to connect a hardware device and a responder for a client to control and receive information from
    the device.

    The Device object is responsible for interpreting data from the device to message the client, and interpreting
    messages from the client to send data to the device.

    The optional command and message queues are interfaces for the client script or application to exchange data with
    the device.

    It is this class's responsibility to enable one- or two-way communication with the device, depending on the
    arguments provided, in a non-blocking fashion.
    """

    def __init__(self, device: Device, message_queue: Queue = None,
                 message_callback: Callable[[int, object], None] = None, name="device-connection"):
        super().__init__()

        # The message queue and the callback are ways to get data from the device back to the client script or
        # application that created this object.  Commands and data to the device are sent through send message.

        self._device = device
        self._interface = device.device_interface
        self._message_callback = message_callback
        self._message_queue = message_queue
        self._cmd_queue: Queue = Queue()

        self._api = DeviceApi(message_callback=message_callback, message_queue=message_queue)
        self._device.api = self._api

        self._name = name

        self._read_limit: int = 1 if HAVE_CAN_DEVICE else math.inf

        # The means of providing non-blocking access to the device.
        self._current_thread = None

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

    def start(self):
        if self._current_thread is None or not self._current_thread.is_alive():
            self._current_thread = Thread(target=self.run)
            self._current_thread.start()

    def join(self):
        if self._current_thread is not None:
            self._current_thread.join()
            self._current_thread = None

    def run(self) -> None:
        logger.debug(f"<{self._name}> thread started")

        while True:
            if not self._run_unconnected():
                break

            if not self._run_connected():
                break

        logger.debug(f"<{self._name}> thread terminated")

    def request_terminate(self):
        """
        Sends a termination request to the device connection queue.  The thread may have not yet terminated when this call
        returns.
        """
        if self._cmd_queue is not None:
            self._cmd_queue.put((_REQUEST_TERMINATE, None, None))

    def send_message(self, kind: int, data: object = None, context: object = None):
        if self._cmd_queue is not None:
            self._cmd_queue.put_nowait((kind, data, context))

    def use_compound_movements(self, data: CompoundMovementDataSet):
        self.send_message(SystemCommandKind.SET_LOAD_PROCEDURE, data.load)
        self.send_message(SystemCommandKind.SET_SEND_PROCEDURE, data.send)

    def use_motor_configurations(self, data: MotorConfigurations):
        self.send_message(SystemCommandKind.WRITE_MOTOR_CONFIGURATION, data.x_config)
        self.send_message(SystemCommandKind.WRITE_MOTOR_CONFIGURATION, data.y_config)
        self.send_message(SystemCommandKind.WRITE_MOTOR_CONFIGURATION, data.z_config)
        self.send_message(SystemCommandKind.WRITE_MOTOR_CONFIGURATION, data.load_config)
        self.send_message(SystemCommandKind.WRITE_MOTOR_CONFIGURATION, data.magnet_config)
        self.send_message(SystemCommandKind.WRITE_MOTOR_CONFIGURATION, data.cover_config)

    def set_load_procedure(self, load_steps: MotorSteps):
        self.send_message(SystemCommandKind.SET_LOAD_PROCEDURE, load_steps)

    def set_send_procedure(self, send_steps: MotorSteps):
        self.send_message(SystemCommandKind.SET_SEND_PROCEDURE, send_steps)

    def set_motor_configuration(self, config):
        assert isinstance(config, ServoConfig) or isinstance(config, StepperConfig)
        self.send_message(SystemCommandKind.WRITE_MOTOR_CONFIGURATION, config)

    def _run_unconnected(self) -> bool:
        while True:
            try:
                cmd, data, context = self._cmd_queue.get_nowait()

                if cmd == _REQUEST_TERMINATE:
                    logger.debug(f"<{self._name}> message: {DeviceThreadMessageKind(cmd).name}")
                    return False
                elif cmd == DeviceThreadMessageKind.CONNECT:
                    logger.debug(f"<{self._name}> message: {DeviceThreadMessageKind(cmd).name}")
                    break
                else:
                    logger.debug(f"<{self._name}> message: {cmd} ignored")
            except Empty:
                # Unclear how universal this is, but the combination of [Jetson, JetPack 5, Ubuntu 20, Python] will
                # significantly slow down the system without explicitly yielding, despite being in its own thread.  This
                # is not the case for other platforms/combinations of the above so may not be apparent when not on the
                # deployment current platform.
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

                if cmd == _REQUEST_TERMINATE:
                    logger.debug(f"<{self._name}> message: {DeviceThreadMessageKind(cmd).name}")
                    return False
                elif cmd == DeviceThreadMessageKind.DISCONNECT:
                    logger.debug(f"<{self._name}> message: {DeviceThreadMessageKind(cmd).name}")
                    break
                else:
                    self._device.notify_message(cmd, data, context)
            except Empty:
                # See sleep comment above.
                time.sleep(0.0001)

        if self._interface.is_open:
            self._device.disconnect()

            self._interface.close()

            logger.debug(f"<{self._name}> interface closed")
        else:
            logger.warning(f"<{self._name} DISCONNECT cmd while device already disconnected")

        return True
