import time

from PySide6.QtCore import QObject, Signal

from autotrainer.device_thread import DeviceThreadMessageKind
from autotrainer.pellet_delivery import PelletDeliveryMessageKind


class PelletReader(QObject):
    version_ready = Signal(str)

    def __init__(self, msg_queue):
        super().__init__()

        self._msg_queue = msg_queue

    def process(self):
        while True:
            try:
                msg = self._msg_queue.get(block=False)

                if msg[0] == DeviceThreadMessageKind.TERMINATE:
                    break

                elif msg[0] == PelletDeliveryMessageKind.VERSION:
                    self.version_ready.emit(msg[1])
            except:
                time.sleep(0.1)
