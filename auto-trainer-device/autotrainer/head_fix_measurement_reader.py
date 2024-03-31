from PySide6.QtCore import QObject, Signal

from autotrainer.device_thread import DeviceThreadMessageKind
from autotrainer.head_fix import HeadFixMessageKind


class HeadFixMeasurementReader(QObject):
    weight_ready = Signal(list)
    switch_ready = Signal(list)
    pressure_ready = Signal(list)

    def __init__(self, msg_queue):
        super().__init__()

        self._msg_queue = msg_queue

    def process(self):
        while True:
            msg = self._msg_queue.get()

            if msg[0] == DeviceThreadMessageKind.TERMINATE:
                break

            if msg[0] == HeadFixMessageKind.MEASUREMENT:
                weights = list()
                switch = list()
                pressure = list()
                for m in msg[1]:
                    weights.append(m.weight)
                    switch.append(m.switch)
                    pressure.append(m.pressure)
                self.weight_ready.emit(weights)
                self.switch_ready.emit(switch)
                self.pressure_ready.emit(pressure)
