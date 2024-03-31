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
    SET_Z = 7


class PelletDelivery(IDeviceListener):
    def __init__(self, api: DeviceApi = None):
        self._api = api

        self._read_buffer = ""
        self._is_waiting_ack = False
        self._is_busy = False
        self._last_command = ""

    @property
    def api(self):
        return self._api

    @api.setter
    def api(self, value: DeviceApi):
        self._api = value

    def connect(self):
        pass

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
            self.send_data(f"K{typing.cast(int, context) * (-1) +  5}x")
        else:
            logger.warning(f"unknown message kind: {kind}")

    def send_data(self, data: str):
        self._is_waiting_ack = True
        self._is_busy = True
        self._last_command = data[0:-1]
        self._api.send_data_str(data)

    def handle_response(self, cmd: str, data: str):
        logger.debug(f"handle response: {cmd} [{data}]")
