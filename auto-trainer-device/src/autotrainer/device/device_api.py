import math

from queue import Queue
from typing import Callable, Optional, Any

from autotrainer.core import get_perf_now
from autotrainer.core.logging import get_verbose_logger

logger = get_verbose_logger(__name__)


MessageCallbackT = Optional[Callable[[int, object], None]]


class DeviceApi:
    """
    DeviceApi is a simple interface for sending messages from the device to higher-level users of the hardware.

    DeviceApi and derivatives implement support for queues, callbacks, or other means of notifying those users,
    allowing actual hardware implementations to have a single means of sending messages ( `DeviceApi`'s
    `send_message()`).
    """

    def __init__(self, message_callback: MessageCallbackT = None, message_queue: Queue = None):
        self._message_callback = message_callback
        self._message_queue = message_queue
        self._prev_perf_c = -math.inf
        self._tot_msgs = 0

    @property
    def message_callback(self) -> MessageCallbackT:
        return self._message_callback

    @message_callback.setter
    def message_callback(self, value: MessageCallbackT):
        self._message_callback = value

    def send_message(self, kind: int, data: Optional[Any] = None):
        """Sends a message identifier and optional data to client script or application"""
        msg_q = self._message_queue
        if msg_q is not None:
            # logger.debug("putting %s", kind)
            msg_q.put((kind, data))

        msg_cb = self._message_callback
        if msg_cb is not None:
            msg_cb(kind, data)

        self._tot_msgs += 1
        p_now = get_perf_now()
        if p_now > self._prev_perf_c + 5:
            logger.debug("%.1f tot msgs / seconds", self._tot_msgs / (p_now - self._prev_perf_c))
            self._prev_perf_c = p_now
            self._tot_msgs = 0
