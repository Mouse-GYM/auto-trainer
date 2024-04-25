import logging
import typing
from enum import IntEnum

from .device_api import DeviceApi
from .device_listener import IDeviceListener

logger = logging.getLogger(__name__)


class PelletDeliveryMessageKind(IntEnum):
    RAW_COMMAND = 0,
    SEND_HOME = 1,
    LOAD_PELLET = 2,
    SEND_PELLET = 3,
    RELEASE_PELLET = 4,
    SET_X = 5,
    SET_Y = 6,
    SET_Z = 7,
    VERSION = 8


class PelletDelivery(IDeviceListener):
    def __init__(self, api: DeviceApi = None):
        self._api = api

        self._read_buffer = ""
        self._is_waiting_ack = False
        self._is_busy = False
        self._last_command = ""

        self._firmware_version = ""

    @property
    def api(self):
        return self._api

    @api.setter
    def api(self, value: DeviceApi):
        self._api = value

    @property
    def firmware_version(self):
        return self._firmware_version

    def connect(self):
        self._api.send_data_str("Fx")

    def disconnect(self):
        pass

    def notify_data(self, data: bytes):
        resp = data.decode()

        if resp == "\n":
            if len(self._read_buffer) > 0:
                self.handle_response(self._last_command, self._read_buffer)
                self._read_buffer = ""
            return

        if resp == "!":
            if not self._is_waiting_ack:
                logger.warning("ack received unexpectedly")
            self._is_waiting_ack = False
        elif resp == "%":
            if not self._is_busy:
                logger.warning("term received unexpectedly")

            logger.debug(f"{self._last_command} command complete")

            if len(self._read_buffer) > 0:
                self.handle_response(self._last_command, self._read_buffer)

            self._last_command = ""
            self._read_buffer = ""

            self._is_busy = False
        else:
            self._read_buffer += resp

    def notify_message(self, kind: PelletDeliveryMessageKind, context: object):
        if kind == PelletDeliveryMessageKind.RAW_COMMAND:
            self.send_data(typing.cast(str, context))
        elif kind == PelletDeliveryMessageKind.SEND_HOME:
            self.send_data("H0x")
        elif kind == PelletDeliveryMessageKind.LOAD_PELLET:
            self.send_data("P0x")
        elif kind == PelletDeliveryMessageKind.SEND_PELLET:
            self.send_data("M0x")
        elif kind == PelletDeliveryMessageKind.RELEASE_PELLET:
            self.send_data("R0x")
        elif kind == PelletDeliveryMessageKind.SET_X:
            self.send_data(f"I{typing.cast(int, context) + 5}x")
        elif kind == PelletDeliveryMessageKind.SET_Y:
            self.send_data(f"J{typing.cast(int, context) + 25}x")
        elif kind == PelletDeliveryMessageKind.SET_Z:
            self.send_data(f"K{typing.cast(int, context) * (-1) + 5}x")
        else:
            logger.warning(f"unknown message kind: {kind}")

    def send_data(self, data: str):
        self._is_waiting_ack = True
        self._is_busy = True
        self._last_command = data[0:-1]
        self._api.send_data_str(data)

    def _set_firmware_version(self, value: str):
        self._firmware_version = value
        self._api.send_message(PelletDeliveryMessageKind.VERSION, self._firmware_version)

    def handle_response(self, cmd: str, data: str):
        logger.debug(f"handle response: {cmd} [{data}]")
        if data.startswith("F"):
            if len(data) > 2:
                if data[1] == "P":
                    self._set_firmware_version(data[2:])
                else:
                    self._set_firmware_version("unknown device")
            else:
                self._set_firmware_version("unknown device id response")
