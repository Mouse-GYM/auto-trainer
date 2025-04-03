import logging
import queue
import typing
from enum import IntEnum, Enum
from queue import Queue

from autotrainer.core import EventManager

from .device_interface import DeviceInterface

from .device import Device, DeviceApi

logger = logging.getLogger(__name__)


class GymDeviceEventKind(IntEnum, Enum):
    deviceCommandSend = 2001,
    deviceCommandAcknowledge = 2002


class GymDeviceMessageKind(IntEnum):
    VERSION = -1,
    ACK = -2,
    READ_CONFIG = -3,
    WRITE_CONFIG = -4,
    SET_LOAD_PROCEDURE = -6,
    SET_SEND_PROCEDURE = -7,

    # deprecated
    SET_HOME_PROCEDURE = -5,

    @classmethod
    def is_member(cls, value):
        return value in cls._value2member_map_


class GymDevice(Device):
    def __init__(self, dev_interface: DeviceInterface, api: DeviceApi):
        super().__init__(dev_interface, api)

        self._read_buffer = ""
        self._is_waiting_ack = False
        self._is_busy = False
        self._last_command = ""
        self._last_command_token = None

        self._firmware_version = ""

        self._command_buffer = Queue()

        self._identifier = ""

    @property
    def firmware_version(self):
        return self._firmware_version

    def notify_data(self, data: typing.Any):
        all_resp = data.decode()

        for resp in all_resp:
            if resp == "\n":
                if len(self._read_buffer) > 0 and self._identifier != "P":
                    self._read_buffer = self._handle_response(self._last_command, self._read_buffer)

                continue

            if resp == "!":
                if not self._is_waiting_ack:
                    logger.warning(f"{self._identifier} ack received unexpectedly")
                self._is_waiting_ack = False
            elif resp == "%":
                if not self._is_busy:
                    logger.warning(f"{self._identifier} term received unexpectedly")

                logger.debug(f"{self._identifier} {self._last_command} command complete")

                if len(self._read_buffer) > 0:
                    self._handle_response(self._last_command, self._read_buffer)

                self._last_command = ""
                self._read_buffer = ""

                EventManager.post_event(GymDeviceEventKind.deviceCommandAcknowledge,
                                        context=self._last_command_token)
                self._api.send_message(GymDeviceMessageKind.ACK, self._last_command_token)

                self._is_busy = False

                try:
                    data, token = self._command_buffer.get_nowait()
                    self._send_data(data, token)
                except queue.Empty:
                    pass
            else:
                self._read_buffer += resp.strip()

    def _send_data(self, data: str, token: object = None):
        if not self._is_busy:
            self._is_waiting_ack = True
            self._is_busy = True
            self._last_command = data[0:-1]
            self._last_command_token = token
            self._api.send_data_str(data)
            EventManager.post_event(GymDeviceEventKind.deviceCommandSend,
                                    context=f"{data}({self._last_command_token})")
        else:
            logger.debug("storing in command buffer")
            self._command_buffer.put((data, token))

        return token

    def _set_firmware_version(self, value: str):
        self._firmware_version = value

    def _handle_response(self, cmd: str, data: str) -> str:

        if len(data) == 0:
            return ""

        if data.startswith("F0"):
            if len(data) > 2:
                if data[2] == self._identifier:
                    self._set_firmware_version(data[3:])
                else:
                    self._set_firmware_version("unknown device")
            else:
                self._set_firmware_version("unknown device id response")

            self._api.send_message(GymDeviceMessageKind.VERSION, self._firmware_version)

            return ""

        return data
