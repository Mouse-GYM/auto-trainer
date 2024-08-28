import os
import logging
import time
from datetime import datetime
from pathlib import Path
from queue import Queue
from threading import Thread
from typing import Callable

from autotrainer.core.project import ProjectInfo

from . import GymDeviceMessageKind
from .device_thread import DeviceThreadMessageKind
from .head_fix import HeadFixMessageKind

logger = logging.getLogger(__name__)


class HeadFixReader(Thread):
    def __init__(self, input_queue: Queue, measurement_callback: Callable[[tuple], None] = None,
                 version_callback: Callable[[str], None] = None, serial_number: str = "00000"):
        super().__init__()

        self._input_queue = input_queue
        self._ack_callback = None
        self._version_callback = version_callback
        self._measurement_callback = measurement_callback
        self._serial_number = serial_number

        self._project_info = None
        self._record_location = None
        self._current_record_hour = -1

        self._measurement_count = 0
        self._start = None

    @property
    def version_callback(self):
        return self._version_callback

    @version_callback.setter
    def version_callback(self, version_callback: Callable[[str], None]):
        self._version_callback = version_callback

    @property
    def measurement_callback(self):
        return self._measurement_callback

    @measurement_callback.setter
    def measurement_callback(self, measurement_callback: Callable[[tuple], None]):
        self._measurement_callback = measurement_callback

    @property
    def ack_callback(self):
        return self._measurement_callback

    @ack_callback.setter
    def ack_callback(self, ack_callback: Callable[[object], None]):
        self._ack_callback = ack_callback

    @property
    def project_info(self) -> ProjectInfo:
        return self._project_info

    @project_info.setter
    def project_info(self, value: ProjectInfo) -> None:
        if self._record_location is not None:
            self._record_location.close()

        self._project_info = value
        self._validate_file()

        self._measurement_count = 0

    def run(self):
        logger.debug("entering HeadFixReader")

        while True:
            msg, data = self._input_queue.get()

            if msg == DeviceThreadMessageKind.TERMINATE:
                break

            if msg == HeadFixMessageKind.STREAM_START:
                self._measurement_count = 0
                self._start = time.perf_counter_ns()
            elif msg == GymDeviceMessageKind.ACK:
                if data and self._ack_callback is not None:
                    self._ack_callback(data)
            elif msg == HeadFixMessageKind.MEASUREMENT:
                weights = list()
                switch = list()
                pressure = list()
                temperature = list()
                humidity = list()
                for m in data:
                    weights.append(m.weight)
                    switch.append(m.switch)
                    pressure.append(m.pressure)
                    temperature.append(m.temperature)
                    humidity.append(m.humidity)
                    if self._record_location is not None:
                        try:
                            file_timestamp = datetime.now()

                            if file_timestamp.hour != self._current_record_hour:
                                if self._record_location is not None:
                                    self._record_location.close()
                                self._validate_file()

                            if self._record_location is not None:
                                self._record_location.write(
                                    f"{time.time()}, {time.perf_counter_ns()}, {m.weight}, {m.switch}, {m.pressure},"
                                    f"{m.temperature}, {m.humidity}\n")
                        except:
                            pass

                if self._measurement_count == 0:
                    self._start = time.perf_counter_ns()

                self._measurement_count += len(data)

                if self._measurement_count % 3000 == 0:
                    logger.debug(f"{(1e9 * self._measurement_count / (time.perf_counter_ns() - self._start)):.1f} mps")

                if self._measurement_callback is not None:
                    self._measurement_callback((weights, switch, pressure, temperature, humidity))
            elif msg == GymDeviceMessageKind.VERSION:
                if self._version_callback is not None:
                    self._version_callback(data)

            time.sleep(0.0001)

        logger.debug("exiting HeadFixReader")

    def _validate_file(self):
        if self._project_info is not None:
            path = self._project_info.get_hourly_source_path("monitor")
            file_name = os.path.join(path.location, f"{path.prefix}.csv")

            try:
                p = Path(path.location)
                p.mkdir(parents=True, exist_ok=True)

                file_existed = os.path.exists(file_name)
                location = open(file_name, "a")
                if not file_existed:
                    location.write("Time, Index, Weight, Switch, Pressure, Temperature, Humidity\n")
                self._current_record_hour = path.hour
                logger.debug(f"saving to {file_name}")
                return location
            except:
                logger.error(f"unable to write to {file_name}")

        return None
