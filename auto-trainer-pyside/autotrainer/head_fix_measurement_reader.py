from __future__ import annotations

import os
import time
from datetime import datetime
from io import TextIOWrapper

from PySide6.QtCore import QObject, Signal

from autotrainer.device_thread import DeviceThreadMessageKind
from autotrainer.head_fix import HeadFixMessageKind


class HeadFixMeasurementReader(QObject):
    weight_ready = Signal(list)
    switch_ready = Signal(list)
    pressure_ready = Signal(list)
    temperature_ready = Signal(list)
    humidity_ready = Signal(list)
    version_ready = Signal(str)

    def __init__(self, msg_queue):
        super().__init__()

        self._msg_queue = msg_queue

        self._record_location: TextIOWrapper | None = None

    @property
    def record_location(self):
        return self._record_location

    @record_location.setter
    def record_location(self, value: str) -> None:
        location = self._record_location

        self._record_location: TextIOWrapper | None = None

        if location is not None:
            location.close()

        if value is not None and os.path.isdir(value):
            try:
                file_timestamp = datetime.now()
                file_name = os.path.join(value, f"{file_timestamp.strftime('%Y%m%d')}_00000_monitor_hr{file_timestamp.strftime('%H')}.csv")
                file_existed = os.path.exists(file_name)
                location = open(file_name, "a")
                if not file_existed:
                    location.write("Index, Weight, Switch, Pressure, Temperature, Humidity\n")
                self._record_location = location
            except:
                pass

    def process(self):
        while True:
            msg = self._msg_queue.get()

            if msg[0] == DeviceThreadMessageKind.TERMINATE:
                break

            if msg[0] == HeadFixMessageKind.MEASUREMENT:
                weights = list()
                switch = list()
                pressure = list()
                temperature = list()
                humidity = list()
                for m in msg[1]:
                    weights.append(m.weight)
                    switch.append(m.switch)
                    pressure.append(m.pressure)
                    temperature.append(m.temperature)
                    humidity.append(m.humidity)
                    if self._record_location is not None:
                        try:
                            self._record_location.write(f"{time.perf_counter_ns()}, {m.weight}, {m.switch}, {m.pressure}," f"{m.temperature}, {m.humidity}\n")
                        except:
                            pass
                self.weight_ready.emit(weights)
                self.switch_ready.emit(switch)
                self.pressure_ready.emit(pressure)
                self.temperature_ready.emit(temperature)
                self.humidity_ready.emit(humidity)
            elif msg[0] == HeadFixMessageKind.VERSION:
                self.version_ready.emit(msg[1])
