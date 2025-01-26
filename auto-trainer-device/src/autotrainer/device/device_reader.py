import logging
import time
from queue import Queue
from threading import Thread

from autotrainer.core import ObservableObject
from autotrainer.device import DeviceThreadMessageKind, GymDeviceMessageKind

logger = logging.getLogger(__name__)


class DeviceReader(ObservableObject):
    FIRMWARE_VERSION = "firmware_version"

    def __init__(self, input_queue: Queue, name: str = "DeviceReader", event_names=()):
        super().__init__(event_names=event_names + ("ack_received",))

        self._input_queue = input_queue

        self._name = name

        self._current_thread = None

    def start(self):
        if self._current_thread is None or not self._current_thread.is_alive():
            self._current_thread = Thread(target=self.run)
            self._current_thread.start()

    def run(self):
        logger.debug(f"<{self._name}>: entering run loop")

        while True:
            msg, data = self._input_queue.get()

            if msg == DeviceThreadMessageKind.TERMINATE:
                break
            elif msg == GymDeviceMessageKind.ACK:
                self.ack_received(data)
            elif msg == GymDeviceMessageKind.VERSION:
                self.property_changed(DeviceReader.FIRMWARE_VERSION, data, None)
            else:
                self.message_received(msg, data)

            time.sleep(0.0001)

        self._current_thread = None

        logger.debug(f"<{self._name}>: exiting run loop")

    def message_received(self, msg, _data):
        pass
