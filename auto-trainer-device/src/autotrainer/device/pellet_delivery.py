import logging
import typing
from enum import IntEnum

from .gym_device import GymDevice, GymDeviceMessageKind
from .device_api import DeviceApi

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

    @classmethod
    def is_member(cls, value):
        return value in cls._value2member_map_


class PelletDelivery(GymDevice):
    def __init__(self, api: DeviceApi = None):
        super().__init__(api)

        self._identifier = "P"

    def notify_message(self, kind: int, data: object, context: object = None):
        if kind == PelletDeliveryMessageKind.RAW_COMMAND:
            self._send_data(typing.cast(str, data), context)
        elif kind == GymDeviceMessageKind.VERSION:
            self._send_data("F0x", context)
        elif kind == PelletDeliveryMessageKind.SEND_HOME:
            self._send_data("H0x", context)
        elif kind == PelletDeliveryMessageKind.LOAD_PELLET:
            self._send_data("P0x", context)
        elif kind == PelletDeliveryMessageKind.SEND_PELLET:
            self._send_data("M0x", context)
        elif kind == PelletDeliveryMessageKind.RELEASE_PELLET:
            self._send_data("R0x", context)
        elif kind == PelletDeliveryMessageKind.SET_X:
            self._send_data(f"I{typing.cast(int, data) + 10}x", context)
        elif kind == PelletDeliveryMessageKind.SET_Y:
            self._send_data(f"J{typing.cast(int, data) + 20}x", context)
        elif kind == PelletDeliveryMessageKind.SET_Z:
            self._send_data(f"K{typing.cast(int, data) + 10}x", context)
        else:
            logger.warning(f"unknown message kind: {kind}")

    def _handle_response(self, cmd: str, data: str) -> str:
        residual = super()._handle_response(cmd, data)

        if len(residual) > 0:
            logger.error(f"ignored data buffer: {data}")

        # Don't let unexpected responses build up the read buffer indefinitely if something went unhandled.
        return ""
