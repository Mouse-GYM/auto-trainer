from __future__ import annotations

import os
import logging
from datetime import datetime
from queue import Queue
from typing import Callable, Optional

import numpy

from autotrainer.core import ProjectInfo, ProjectInterval
from autotrainer.core import PerfMonitor, SystemStatusMessageKind
from .headbar_pressure_monitor import HeadbarPressureMonitor

from .device_reader import DeviceReader
from .load_cell_monitor import LoadCellMonitor
from .load_cell_tare_monitor import LoadCellTareMonitor

logger = logging.getLogger(__name__)


class HeadFixReader(DeviceReader):
    # This class currently responds to messages coming from the hardware that are specific to the tunnel status and
    # behavior as well as sensor data.

    # TODO: This should be refactored to better differentiate between tunnel/head fix status and behavior and the sensor
    # data responses.  This is an artifact of when the original hardware had separate devices for the tunnel and pellet
    # delivery and the sensor data was tied to the tunnel device specifically.
    def __init__(self, input_queue: Queue):
        super().__init__(input_queue, name="HeadFixReader")

        self._measurement_callback = None

        self._project_info: Optional[ProjectInfo] = None
        self._interval = ProjectInterval.HOUR
        self._record_file = None
        self._current_record_interval = -1

        self._had_write_error = False

        self._is_headbar_engaged = False

        self._is_load_cell_engaged = False
        self._load_cell_monitor = LoadCellMonitor()
        self._load_cell_monitor.property_changed += self._load_cell_property_changed

        self._is_force_detector_engaged = False
        self._force_detector = HeadbarPressureMonitor()

        self._tare_detector = LoadCellTareMonitor()
        self._tare_callback = None

        self._perf_monitor = PerfMonitor(name="<HeadFixReader>", units="mps", report_count=3000)

    @property
    def project_info(self) -> ProjectInfo:
        return self._project_info

    @project_info.setter
    def project_info(self, value: ProjectInfo) -> None:
        if self._record_file is not None:
            self._record_file.close()

        self._project_info = value
        self._update_record_file()

        self._perf_monitor.reset()

    @property
    def interval(self) -> ProjectInterval:
        return self._interval

    @interval.setter
    def interval(self, value: ProjectInterval) -> None:
        self._interval = value

    @property
    def measurement_callback(self):
        return self._measurement_callback

    @measurement_callback.setter
    def measurement_callback(self, measurement_callback: Callable[[tuple], None]) -> None:
        self._measurement_callback = measurement_callback

    @property
    def tare_callback(self):
        return self._tare_callback

    @tare_callback.setter
    def tare_callback(self, tare_callback: Callable[[], None]) -> None:
        self._tare_callback = tare_callback

    @property
    def is_headbar_engaged(self):
        return self._is_headbar_engaged

    @property
    def is_headbar_pressure_engaged(self):
        return self._is_force_detector_engaged

    @is_headbar_pressure_engaged.setter
    def is_headbar_pressure_engaged(self, value: bool):
        self._is_force_detector_engaged = self._on_property_changed("is_force_detector_engaged", value,
                                                                    self._is_force_detector_engaged)

    @property
    def load_cell_monitor(self):
        return self._load_cell_monitor

    @property
    def tare_detector(self):
        return self._tare_detector

    @property
    def force_detector(self):
        return self._force_detector

    def message_received(self, msg, data):
        if msg == SystemStatusMessageKind.STREAM_START:
            self._perf_monitor.reset()
        elif msg == SystemStatusMessageKind.MEASUREMENT:
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
                            f"{m.when}, {m.timestamp}, {m.weight}, {m.switch}, {m.pressure},"
                            f"{m.temperature}, {m.humidity}\n")
                    except Exception as e:
                        # This could be too much if something major is wrong.  Just output once per file rotation.
                        if not self._had_write_error:
                            logger.error(f"<{self._name}>: unable to write: {e}")
                            self._had_write_error = True

            # Measurement callback.
            if self._measurement_callback is not None:
                self._measurement_callback((weights, switch, pressure, temperature, humidity))

            # Load cell monitor.
            self._load_cell_monitor.update(numpy.mean(weights), data[0].when, data[0].timestamp)

            # Headbar monitor.
            self._is_headbar_engaged = self._on_property_changed("is_headbar_engaged", numpy.mean(switch) > 0.5,
                                                                 self._is_headbar_engaged)

            # Force detector.
            self._is_force_detector_engaged = self._on_property_changed("is_force_detector_engaged",
                                                                        self._force_detector.update(pressure,
                                                                                                    data[0].when,
                                                                                                    data[0].timestamp),
                                                                        self._is_force_detector_engaged)

            if self._tare_detector.update(weights) and self._tare_callback is not None:
                self._tare_callback()

            # Performance monitoring.
            self._perf_monitor.add_cycles(len(data))

    def _load_cell_property_changed(self, _name, value, _):
        self._is_load_cell_engaged = self._on_property_changed("is_load_cell_engaged", value,
                                                               self._is_load_cell_engaged)

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
