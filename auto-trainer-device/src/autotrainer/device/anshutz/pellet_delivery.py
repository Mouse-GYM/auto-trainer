import logging
import typing

from autotrainer.core.message import SystemStatusMessageKind, SystemCommandKind

from ..device_api import DeviceApi

from .serial_interface import SerialInterface
from .gym_device import GymDevice

logger = logging.getLogger(__name__)


class PelletDelivery(GymDevice):
    def __init__(self, port: str, api: DeviceApi = None):
        super().__init__(SerialInterface(port), api)

        self._identifier = "P"

        # This hardware does not support status messages for servo, stepper, or DIO.  For commands that may change these
        # values, store the expected value, assumes it was successful, and send a status message after it completes and
        # has been acknowledged.  This allows scripts/apps to see the updates they would expect from the new hardware.
        self._commands_with_status = {}

        # This hardware does not report motor positions.  The tracks the last X, Y, Z command values, which translate
        # to the send location on the hardware.  This allows a crude form of reporting positions.  It is less for the
        # accuracy of the position with the hardware and more to fulfill the position status behavior to avoid
        # special casing all users for differences in hardware.
        self._send_x = 0
        self._send_y = 0
        self._send_z = 0

    def notify_message(self, kind: int, data: object, context: object = None):
        if kind == SystemCommandKind.RAW_COMMAND:
            self._send_data(typing.cast(str, data), context)
        elif kind == SystemCommandKind.REQUEST_VERSION:
            self._send_data("F0x", context)
        elif kind == SystemCommandKind.SEND_HOME:
            self._send_data("H0x", context)
            if context is not None:
                self._commands_with_status[context] = (SystemCommandKind.SEND_HOME, None)
        elif kind == SystemCommandKind.LOAD_PELLET:
            self._send_data("P0x", context)
            self.api.send_message(SystemStatusMessageKind.PELLET_LOAD, 180)
            if context is not None:
                self._commands_with_status[context] = (SystemCommandKind.LOAD_PELLET, None)
        elif kind == SystemCommandKind.SEND_PELLET:
            self._send_data("M0x", context)
            if context is not None:
                self._commands_with_status[context] = (SystemCommandKind.SEND_PELLET, None)
        elif kind == SystemCommandKind.RELEASE_PELLET:
            self._send_data("R0x", context)
            if context is not None:
                self._commands_with_status[context] = (SystemCommandKind.RELEASE_PELLET, None)
        elif kind == SystemCommandKind.COVER_PELLET:
            self._send_data("Q0x", context)
            if context is not None:
                self._commands_with_status[context] = (SystemCommandKind.COVER_PELLET, None)
        elif kind == SystemCommandKind.SET_X:
            if isinstance(data, float):
                val = int(data)
            else:
                val = typing.cast(int, data)
            self._send_x = val
            self._send_data(f"I{self._send_x + 10}x", context)
            if context is not None:
                self._commands_with_status[context] = (SystemCommandKind.SET_X, val)
        elif kind == SystemCommandKind.SET_Y:
            if isinstance(data, float):
                val = int(data)
            else:
                val = typing.cast(int, data)
            self._send_y = val
            self._send_data(f"J{self._send_y + 20}x", context)
            if context is not None:
                self._commands_with_status[context] = (SystemCommandKind.SET_Y, val)
        elif kind == SystemCommandKind.SET_Z:
            if isinstance(data, float):
                val = int(data)
            else:
                val = typing.cast(int, data)
            self._send_z = val
            self._send_data(f"K{self._send_z + 10}x", context)
            if context is not None:
                self._commands_with_status[context] = (SystemCommandKind.SET_Z, val)
            elif kind == SystemCommandKind.MOVE_X:
                if isinstance(data, float):
                    val = int(data)
                else:
                    val = typing.cast(int, data)
                self._send_data(f"I{val}x", context)
                if context is not None:
                    self._commands_with_status[context] = (SystemCommandKind.MOVE_X, val)
            elif kind == SystemCommandKind.MOVE_Y:
                if isinstance(data, float):
                    val = int(data)
                else:
                    val = typing.cast(int, data)
                self._send_data(f"J{val}x", context)
                if context is not None:
                    self._commands_with_status[context] = (SystemCommandKind.MOVE_Y, val)
            elif kind == SystemCommandKind.MOVE_Z:
                if isinstance(data, float):
                    val = int(data)
                else:
                    val = typing.cast(int, data)
                self._send_data(f"K{val}x", context)
                if context is not None:
                    self._commands_with_status[context] = (SystemCommandKind.MOVE_Z, val)
        elif kind == SystemCommandKind.PLAY_TONE:
            self._send_data(f"N{typing.cast(int, data)}x", context)
        elif kind == SystemCommandKind.SET_SEND_PELLET_PROCEDURE or \
            kind == SystemCommandKind.SET_LOAD_PELLET_PROCEDURE or \
            kind == SystemCommandKind.SET_COVER_PELLET_PROCEDURE or \
            kind == SystemCommandKind.SET_RELEASE_PELLET_PROCEDURE or \
            kind == SystemCommandKind.WRITE_MOTOR_CONFIGURATION:
            pass
        else:
            logger.warning(f"unknown message kind: {kind}")

    def _acknowledge_command(self, token: object):
        response = self._commands_with_status.pop(token, None)

        super()._acknowledge_command(token)

        if response is not None:
            if response[0] == SystemCommandKind.SEND_HOME:
                self.api.send_message(SystemStatusMessageKind.PELLET_X, 0)
                self.api.send_message(SystemStatusMessageKind.PELLET_Y, 0)
                self.api.send_message(SystemStatusMessageKind.PELLET_Z, 0)
            elif response[0] == SystemCommandKind.SEND_PELLET:
                self.api.send_message(SystemStatusMessageKind.PELLET_X, self._send_x)
                self.api.send_message(SystemStatusMessageKind.PELLET_Y, self._send_y)
                self.api.send_message(SystemStatusMessageKind.PELLET_Z, self._send_z)
            elif response[0] == SystemCommandKind.LOAD_PELLET:
                self.api.send_message(SystemStatusMessageKind.PELLET_X, 0)
                self.api.send_message(SystemStatusMessageKind.PELLET_Y, 0)
                self.api.send_message(SystemStatusMessageKind.PELLET_Z, 0)
                self.api.send_message(SystemStatusMessageKind.PELLET_LOAD, 0)
            elif response[0] == SystemCommandKind.COVER_PELLET:
                self.api.send_message(SystemStatusMessageKind.PELLET_COVER, 40)
            elif response[0] == SystemCommandKind.RELEASE_PELLET:
                self.api.send_message(SystemStatusMessageKind.PELLET_COVER, 0)
            elif response[0] == SystemCommandKind.MOVE_X:
                self.api.send_message(SystemStatusMessageKind.PELLET_X, response[1])
            elif response[0] == SystemCommandKind.MOVE_Y:
                self.api.send_message(SystemStatusMessageKind.PELLET_Y, response[1])
            elif response[0] == SystemCommandKind.MOVE_Z:
                self.api.send_message(SystemStatusMessageKind.PELLET_Z, response[1])

    def _handle_response(self, cmd: str, data: str) -> str:
        residual = super()._handle_response(cmd, data)

        if len(residual) > 0:
            logger.info(f"ignored data buffer: {data}")

        # Don't let unexpected responses build up the read buffer indefinitely if something went unhandled.
        return ""
