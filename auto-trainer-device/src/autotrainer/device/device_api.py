import math

from queue import Queue
from typing import Callable, Optional, Any

from events import Events

from autotrainer.core import get_perf_now
from autotrainer.core.logging import get_verbose_logger
from autotrainer.core import ObservableObject
from autotrainer.core.observable_object import EventHandler

logger = get_verbose_logger(__name__)


MessageCallbackT = Callable[[int, object], None]


class DeviceApiEvents(Events):
    message_callback: EventHandler[MessageCallbackT]


class DeviceApi:
    """
    DeviceApi is a simple interface for sending messages from the device to higher-level users of the hardware.

    DeviceApi and derivatives implement support for queues, callbacks, or other means of notifying those users,
    allowing actual hardware implementations to have a single means of sending messages ( `DeviceApi`'s
    `send_message()`).
    """

    def __init__(self, message_queue: Queue = None):
        super().__init__()
        self._message_queue = message_queue
        self._prev_perf_c = -math.inf
        self._tot_msgs = 0
        self._events = DeviceApiEvents()

    @property
    def message_callback(self) -> EventHandler[MessageCallbackT]:
        return self._events.message_callback

    @message_callback.setter
    def message_callback(self, value: EventHandler[MessageCallbackT]):
        self._events.message_callback = value

    def send_message(self, kind: int, data: Optional[Any] = None):
        """Sends a message identifier and optional data to client script or application"""
        msg_q = self._message_queue
        if msg_q is not None:
            # logger.debug("putting %s", kind)
            msg_q.put((kind, data))

        self._events.message_callback(kind, data)

        self._tot_msgs += 1
        p_now = get_perf_now()
        if p_now > self._prev_perf_c + 5:
            logger.debug("%.1f tot msgs / seconds", self._tot_msgs / (p_now - self._prev_perf_c))
            self._prev_perf_c = p_now
            self._tot_msgs = 0
