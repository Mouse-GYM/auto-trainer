import logging
import time
from queue import Queue
from threading import Thread

from autotrainer.core import ObservableObject, SystemStatusMessageKind

logger = logging.getLogger(__name__)

TERMINATE = -1001


class DeviceReader(ObservableObject):
    """
    Base class for handling messages that come from the hardware.  It has two primary purposes.

    The first is to ensure that any middle-management of information or data happens in a separate thread from both the
    hardware interfacing and any downstream consumers without requiring either the hardware code or the downstream code
    to know whether that is taken care of or not - other than knowing to call start() on this object when ready to
    receive messages.

    The second is to insulate downstream consumers from any specifics of the hardware implementation such as how
    commands are acknowledged, what capabilities different versions of the hardware may have, etc.  Subclasses for
    elements such as pellet delivery, tunnel behavior, and sensor measurements present properties (with change
    notification), callbacks, and other means of making the data available in a consistent format that downstream
    consumers care about rather than as specifically implemented the hardware.
    """
    FIRMWARE_VERSION = "firmware_version"

    def __init__(self, input_queue: Queue, name: str = "DeviceReader", event_names=()):
        super().__init__(event_names=event_names + ("ack_received",))

        self._input_queue = input_queue

        self._name = name

        self._current_thread = None

    @property
    def input_queue(self) -> Queue:
        return self._input_queue

    def start(self):
        if self._current_thread is None or not self._current_thread.is_alive():
            self._current_thread = Thread(target=self.run)
            self._current_thread.start()

    def run(self):
        logger.debug(f"<{self._name}>: entering run loop")

        while True:
            msg, data = self._input_queue.get()

            if msg == TERMINATE:
                break
            elif msg == SystemStatusMessageKind.ACK:
                self.ack_received(data)
            elif msg == SystemStatusMessageKind.VERSION:
                self.property_changed(DeviceReader.FIRMWARE_VERSION, data, None)
            else:
                self.message_received(msg, data)

            time.sleep(0.0001)

        self._current_thread = None

        logger.debug(f"<{self._name}>: exiting run loop")

    def message_received(self, msg, _data):
        pass

    def request_terminate(self):
        """
        Sends a termination request to the device reader queue.  The thread may have not yet terminated when this call
        returns.
        """
        if self._input_queue is not None:
            self._input_queue.put((TERMINATE, None))
