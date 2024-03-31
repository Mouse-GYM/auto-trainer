from typing import Callable

from . device_interface import IDeviceInterface


class DeviceApi:
    def __init__(self, interface: IDeviceInterface, message_callback: Callable[[int, object], None] = None):
        self._interface = interface
        self._message_callback = message_callback

    def send_data(self, value: bytes):
        self._interface.write(value)

    def send_data_str(self, value: str):
        self._interface.write_str(value)

    def send_message(self, kind: int, context: object):
        self._message_callback(kind, context)
