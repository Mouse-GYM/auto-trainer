from queue import Queue
from typing import Callable


class DeviceApi:
    """
    DeviceApi is a simple interface for sending messages from the device to higher-level users of the hardware.

    DeviceApi and derivatives implement support for queues, callbacks, or other means of notifying those users,
    allowing actual hardware implementations to have a single means of sending messages ( `DeviceApi`'s
    `send_message()`).
    """

    def __init__(self, message_callback: Callable[[int, object], None] = None, message_queue: Queue = None):
        self._message_callback = message_callback
        self._message_queue = message_queue

    def send_message(self, kind: int, context: object):
        """Sends a message identifier and optional data to client script or application"""
        if self._message_queue is not None:
            self._message_queue.put((kind, context))

        if self._message_callback is not None:
            self._message_callback(kind, context)
