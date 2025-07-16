import logging
import math
import time
from queue import Queue, Empty
from threading import Thread
from typing import Callable

from autotrainer.core import MotorConfigurations, SystemCommandKind

from .can_device import HAVE_CAN_DEVICE
from .device import Device
from .device_api import DeviceApi
from .device_interface import ServoConfig, StepperConfig
from .device_connection_protocol import DeviceConnectionProtocol
from .motor_steps import CompoundMovementDataSet, MotorSteps
from autotrainer.core.logging import get_verbose_logger

logger = get_verbose_logger(__name__)

_REQUEST_CONNECT = -1002
_REQUEST_DISCONNECT = -1003


class DeviceConnection(DeviceConnectionProtocol):
    """
    Convenience class to connect a hardware device and a responder for a client to control and receive information from
    the device.

    The Device object is responsible for interpreting data from the device to message the client, and interpreting
    messages from the client to send data to the device.

    The optional message queue and callback are interfaces for the client script or application to exchange data with
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

        self._read_limit: int = 25 if HAVE_CAN_DEVICE else math.inf

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

    def join(self):
        # TODO this is for legacy compatibility when the connection was exposed directly as a thread for clients that
        #  wanted to know when the connection was guaranteed to be terminated.  This should be accommodated a different
        #  way - see TODOs in request_(dis)connect.

        if self._current_thread is not None:
            self._current_thread.join()
            self._current_thread = None

    def request_connect(self):
        """
        Attempts to establish a connection to the device.  This is framed as a request for two reasons.  Even in the
        case of a successful connection, it will not have been fully established at the time this call returns.  The
        second reason is that the connection attempt may fail.
        """
        # TODO provide a mechanism for the caller to be notified when a connection attempt succeeds or fails.  Could be
        #  an optional callback provided in this call, a dedicated callback, an observable property, etc.
        self._start()

        if self._cmd_queue is not None:
            self._cmd_queue.put((_REQUEST_CONNECT, None, None))

    def request_disconnect(self):
        """
        Sends a disconnect request to the device connection queue.  It is framed as a request because the device may not
        be disconnected and relevant objects yet disposed when this call returns.  However, anything running and
        allocated with be terminated and disposed.
        """
        # TODO provide a mechanism for the caller to be notified when disconnection is complete.
        if self._cmd_queue is not None:
            self._cmd_queue.put((_REQUEST_DISCONNECT, None, None))

    def send_message(self, kind: int, data: object = None, context: object = None):
        if self._cmd_queue is not None:
            self._cmd_queue.put_nowait((kind, data, context))

    def use_compound_movements(self, data: CompoundMovementDataSet):
        self.send_message(SystemCommandKind.SET_LOAD_PELLET_PROCEDURE, data.load_pellet)
        self.send_message(SystemCommandKind.SET_SEND_PELLET_PROCEDURE, data.send_pellet)
        self.send_message(SystemCommandKind.SET_COVER_PELLET_PROCEDURE, data.cover_pellet)
        self.send_message(SystemCommandKind.SET_RELEASE_PELLET_PROCEDURE, data.release_pellet)

    def use_motor_configurations(self, data: MotorConfigurations):
        logger.notice("Setting motor configurations")
        self.send_message(SystemCommandKind.WRITE_MOTOR_CONFIGURATION, data.x_config)
        self.send_message(SystemCommandKind.WRITE_MOTOR_CONFIGURATION, data.y_config)
        self.send_message(SystemCommandKind.WRITE_MOTOR_CONFIGURATION, data.z_config)
        self.send_message(SystemCommandKind.WRITE_MOTOR_CONFIGURATION, data.load_config)
        self.send_message(SystemCommandKind.WRITE_MOTOR_CONFIGURATION, data.magnet_config)
        self.send_message(SystemCommandKind.WRITE_MOTOR_CONFIGURATION, data.cover_config)
        self.send_message(SystemCommandKind.WRITE_MOTOR_CONFIGURATION, data.gate_config)

    def set_load_procedure(self, load_steps: MotorSteps):
        self.send_message(SystemCommandKind.SET_LOAD_PELLET_PROCEDURE, load_steps)

    def set_send_procedure(self, send_steps: MotorSteps):
        self.send_message(SystemCommandKind.SET_SEND_PELLET_PROCEDURE, send_steps)

    def set_cover_procedure(self, cover_steps: MotorSteps):
        self.send_message(SystemCommandKind.SET_COVER_PELLET_PROCEDURE, cover_steps)

    def set_release_procedure(self, release_steps: MotorSteps):
        self.send_message(SystemCommandKind.SET_RELEASE_PELLET_PROCEDURE, release_steps)

    def set_motor_configuration(self, config):
        assert isinstance(config, ServoConfig) or isinstance(config, StepperConfig)
        self.send_message(SystemCommandKind.WRITE_MOTOR_CONFIGURATION, config)

    def _start(self):
        if self._current_thread is None or not self._current_thread.is_alive():
            self._current_thread = Thread(target=self._run, name=self._name)
            self._current_thread.start()

    def _run(self) -> None:
        logger.debug(f"<{self._name}> thread started")

        while True:
            if not self._run_unconnected():
                break

            if not self._run_connected():
                break

        logger.debug(f"<{self._name}> thread terminated")

    def _run_unconnected(self) -> bool:
        logger.info("running unconnected")
        while True:
            try:
                cmd, data, context = self._cmd_queue.get(timeout=0.1)
                self._cmd_queue.task_done()
            except Empty:
                continue

            if cmd == _REQUEST_DISCONNECT:
                logger.debug(f"<{self._name}> message: _REQUEST_DISCONNECT")
                return False
            elif cmd == _REQUEST_CONNECT:
                logger.debug(f"<{self._name}> message: _REQUEST_CONNECT")
                break
            else:
                logger.debug(f"<{self._name}> message: {cmd} ignored")

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
            except Exception as err:
                logger.exception("<%s>: %s", self._name, err)
                return False
        else:
            logger.warning(f"<{self._name}>CONNECT cmd while device already open")

        return True

    def _run_connected(self) -> bool:
        logger.info("running connected")
        t_next_cmd_queue_read = time.time()
        while True:
            # Data from the device for the device listener to process.
            tot_msg_read = 0
            if self._interface.can_read():
                messages = self._interface.read(self._read_limit, collect_ms=10)
                n = len(messages)
                if n > 0:
                    self._device.notify_data(messages)
                    tot_msg_read += n

            t_now = time.time()
            if t_now > t_next_cmd_queue_read:
                t_next_cmd_queue_read = t_now + 0.05
                # Messages from the client of this class to control the device listener (or this class, such as TERMINATE).
                try:
                    cmd, data, context = self._cmd_queue.get_nowait()
                except Empty:
                    pass
                else:
                    if cmd == _REQUEST_DISCONNECT:
                        self._cmd_queue.task_done()
                        logger.debug(f"<{self._name}> message: _REQUEST_DISCONNECT")
                        break
                    else:
                        self._device.notify_message(cmd, data, context)
                        self._cmd_queue.task_done()

        if self._interface.is_open:
            self._device.disconnect()

            self._interface.close()

            logger.debug(f"<{self._name}> interface closed")
        else:
            logger.warning(f"<{self._name} DISCONNECT cmd while device already disconnected")

        return False
