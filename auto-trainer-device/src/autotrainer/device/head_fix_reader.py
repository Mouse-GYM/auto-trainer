from __future__ import annotations

import os
import logging
import time
from datetime import datetime
from queue import Queue
from threading import Thread
from typing import Callable

from autotrainer.core.project import ProjectInfo, ProjectInterval

from . import GymDeviceMessageKind
from .device_thread import DeviceThreadMessageKind
from .head_fix import HeadFixMessageKind

logger = logging.getLogger(__name__)


class HeadFixReader(Thread):
    def __init__(self, input_queue: Queue, measurement_callback: Callable[[tuple], None] = None,
                 version_callback: Callable[[str], None] = None, serial_number: str = "00000"):
        super().__init__()

        self._name = "HeadFixReader"

        self._input_queue = input_queue
        self._ack_callback = None
        self._version_callback = version_callback
        self._measurement_callback = measurement_callback
        self._serial_number = serial_number

        self._project_info: ProjectInfo | None = None
        self._interval = ProjectInterval.HOUR
        self._record_file = None
        self._current_record_interval = -1

        self._had_write_error = False

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
        if self._record_file is not None:
            self._record_file.close()

        self._project_info = value
        self._update_record_file()

        self._measurement_count = 0

    @property
    def interval(self) -> ProjectInterval:
        return self._interval

    @interval.setter
    def interval(self, value: ProjectInterval) -> None:
        self._interval = value

    def run(self):
        logger.debug(f"<{self._name}>: entering run loop")

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

                if self._record_file is not None:
                    file_timestamp = datetime.now()

                    needs_update = file_timestamp.hour != self._current_record_interval \
                        if self._interval == ProjectInterval.HOUR \
                        else file_timestamp.minute != self._current_record_interval

                    if needs_update:
                        self._update_record_file()

                for m in data:
                    weights.append(m.weight)
                    switch.append(m.switch)
                    pressure.append(m.pressure)
                    temperature.append(m.temperature)
                    humidity.append(m.humidity)

                    if self._record_file is not None:
                        try:
                            self._record_file.write(
                                f"{time.time()}, {time.perf_counter_ns()}, {m.weight}, {m.switch}, {m.pressure},"
                                f"{m.temperature}, {m.humidity}\n")
                        except Exception as e:
                            # This could be too much if something major is wrong.  Just output once per file rotation.
                            if not self._had_write_error:
                                logger.error(f"<{self._name}>: unable to write: {e}")
                                self._had_write_error = True

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

        logger.debug(f"<{self._name}>: exiting run loop")

    def _update_record_file(self) -> None:
        if self._record_file is not None:
            try:
                self._record_file.close()
            except:
                pass

            self._record_file = None

        if self._project_info is not None:
            interval_file_info = self._project_info.get_monitor_file(interval=self._interval)

            if interval_file_info is None:
                logger.error(f"<{self._name}>: unable to write to expected monitor file location")
                return

            try:
                file_existed = os.path.exists(interval_file_info.file)

                location = open(interval_file_info.file, "a")

                if not file_existed:
                    location.write("Time, Index, Weight, Switch, Pressure, Temperature, Humidity\n")

                self._current_record_interval = interval_file_info.current_interval
                self._record_file = location
                logger.info(f"<{self._name}>: saving to {interval_file_info.file}")
                self._had_write_error = False
            except:
                logger.error(f"<{self._name}>: unable to write to {interval_file_info.file}")

        return None
