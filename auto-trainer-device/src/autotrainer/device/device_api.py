import typing
from queue import Queue
from typing import Callable

from .device_interface import DeviceInterface


class DeviceApi:
    """A set of client- and interface-independent methods for a device listener to communicate up and downstream.

    A DeviceApi separates the mechanism for sending data to the physical device and for sending messages to a script
    or application from the device from a Device subclass itself.

    The default implementation provided here assumes a DeviceInterface implementation for sending data to the device
    and a simple callback function to be called and/or queue to filled with messages and responses from the Device.
    Other implementations could use different methods.
    """

    def __init__(self, interface: DeviceInterface = None, message_callback: Callable[[int, object], None] = None,
                 message_queue: Queue = None):
        self._interface = interface
        self._message_callback = message_callback
        self._message_queue = message_queue

    @property
    def interface(self) -> DeviceInterface:
        return self._interface

    def send_data(self, value: typing.Any):
        """Sends data to the device"""
        if self._interface is not None:
            self._interface.write(value)

    def send_data_str(self, value: str):
        """Sends data to the device"""
        if self._interface is not None:
            self._interface.write_str(value)

    def send_message(self, kind: int, context: object):
        """Sends a message identifier and optional data to client script or application"""
        if self._message_callback is not None:
            self._message_callback(kind, context)

        if self._message_queue is not None:
            self._message_queue.put((kind, context))
