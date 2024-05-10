from typing import Callable

from . device_interface import IDeviceInterface


class DeviceApi:
    """A set of client- and interface-independent methods for a device listener to communicate up and downstream"""
    def __init__(self, interface: IDeviceInterface, message_callback: Callable[[int, object], None] = None):
        self._interface = interface
        self._message_callback = message_callback

    def send_data(self, value: bytes):
        """Sends data to the device"""
        self._interface.write(value)

    def send_data_str(self, value: str):
        """Sends data to the device"""
        self._interface.write_str(value)

    def send_message(self, kind: int, context: object):
        """Sends a message identifier and optional data to client script or application"""
        self._message_callback(kind, context)
