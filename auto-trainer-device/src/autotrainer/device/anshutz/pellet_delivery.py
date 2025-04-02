import logging
import typing

from autotrainer.core.message import SystemStatusMessageKind

from ..device_api import DeviceApi
from ..pellet_delivery_message_kind import PelletDeliveryMessageKind

from .serial_interface import SerialInterface
from .gym_device import GymDevice
from ..device_message_kind import GymDeviceMessageKind

logger = logging.getLogger(__name__)


class PelletDelivery(GymDevice):
    def __init__(self, port: str, api: DeviceApi = None):
        super().__init__(SerialInterface(port), api)

        self._identifier = "P"

        self._commands_with_status = {}

        self._send_x = 0
        self._send_y = 2
        self._send_z = 0

    def notify_message(self, kind: int, data: object, context: object = None):
        if kind == PelletDeliveryMessageKind.RAW_COMMAND:
            self._send_data(typing.cast(str, data), context)
        elif kind == GymDeviceMessageKind.VERSION:
            self._send_data("F0x", context)
        elif kind == PelletDeliveryMessageKind.SEND_HOME:
            self._send_data("H0x", context)
            if context is not None:
                self._commands_with_status[context] = (PelletDeliveryMessageKind.SEND_HOME, None)
        elif kind == PelletDeliveryMessageKind.LOAD_PELLET:
            self._send_data("P0x", context)
            self.api.send_message(SystemStatusMessageKind.PELLET_LOAD, 180)
            if context is not None:
                self._commands_with_status[context] = (PelletDeliveryMessageKind.LOAD_PELLET, None)
        elif kind == PelletDeliveryMessageKind.SEND_PELLET:
            self._send_data("M0x", context)
            if context is not None:
                self._commands_with_status[context] = (PelletDeliveryMessageKind.SEND_PELLET, None)
        elif kind == PelletDeliveryMessageKind.RELEASE_PELLET:
            self._send_data("R0x", context)
            if context is not None:
                self._commands_with_status[context] = (PelletDeliveryMessageKind.RELEASE_PELLET, None)
        elif kind == PelletDeliveryMessageKind.COVER_PELLET:
            self._send_data("Q0x", context)
            if context is not None:
                self._commands_with_status[context] = (PelletDeliveryMessageKind.COVER_PELLET, None)
        elif kind == PelletDeliveryMessageKind.SET_X:
            self._send_x = typing.cast(int, data)
            self._send_data(f"I{self._send_x + 10}x", context)
            if context is not None:
                self._commands_with_status[context] = (PelletDeliveryMessageKind.SET_X, data)
        elif kind == PelletDeliveryMessageKind.SET_Y:
            self._send_y = typing.cast(int, data)
            self._send_data(f"J{self._send_y + 20}x", context)
            if context is not None:
                self._commands_with_status[context] = (PelletDeliveryMessageKind.SET_Y, data)
        elif kind == PelletDeliveryMessageKind.SET_Z:
            self._send_z = typing.cast(int, data)
            self._send_data(f"K{self._send_z + 10}x", context)
            if context is not None:
                self._commands_with_status[context] = (PelletDeliveryMessageKind.SET_Z, data)
        elif kind == GymDeviceMessageKind.SET_SEND_PROCEDURE or \
                kind == GymDeviceMessageKind.SET_LOAD_PROCEDURE or \
                kind == GymDeviceMessageKind.READ_CONFIG or \
                kind == GymDeviceMessageKind.WRITE_CONFIG:
            pass
        else:
            logger.warning(f"unknown message kind: {kind}")

    def _command_acknowledged(self, token: object):
        response = self._commands_with_status.pop(token, None)

        super()._command_acknowledged(token)

        if response is not None:
            if response[0] == PelletDeliveryMessageKind.SEND_HOME:
                self.api.send_message(SystemStatusMessageKind.PELLET_X, 0)
                self.api.send_message(SystemStatusMessageKind.PELLET_Y, 0)
                self.api.send_message(SystemStatusMessageKind.PELLET_Z, 0)
            elif response[0] == PelletDeliveryMessageKind.SEND_PELLET:
                self.api.send_message(SystemStatusMessageKind.PELLET_X, self._send_x)
                self.api.send_message(SystemStatusMessageKind.PELLET_Y, self._send_y)
                self.api.send_message(SystemStatusMessageKind.PELLET_Z, self._send_z)
            elif response[0] == PelletDeliveryMessageKind.LOAD_PELLET:
                self.api.send_message(SystemStatusMessageKind.PELLET_X, 0)
                self.api.send_message(SystemStatusMessageKind.PELLET_Y, 0)
                self.api.send_message(SystemStatusMessageKind.PELLET_Z, 0)
                self.api.send_message(SystemStatusMessageKind.PELLET_LOAD, 0)
            elif response[0] == PelletDeliveryMessageKind.COVER_PELLET:
                self.api.send_message(SystemStatusMessageKind.PELLET_COVER, 40)
            elif response[0] == PelletDeliveryMessageKind.RELEASE_PELLET:
                self.api.send_message(SystemStatusMessageKind.PELLET_COVER, 0)
            elif response[0] == PelletDeliveryMessageKind.SET_X:
                self.api.send_message(SystemStatusMessageKind.PELLET_X, response[1])
            elif response[0] == PelletDeliveryMessageKind.SET_Y:
                self.api.send_message(SystemStatusMessageKind.PELLET_Y, response[1])
            elif response[0] == PelletDeliveryMessageKind.SET_Z:
                self.api.send_message(SystemStatusMessageKind.PELLET_Z, response[1])

    def _handle_response(self, cmd: str, data: str) -> str:
        residual = super()._handle_response(cmd, data)

        if len(residual) > 0:
            logger.info(f"ignored data buffer: {data}")

        # Don't let unexpected responses build up the read buffer indefinitely if something went unhandled.
        return ""
