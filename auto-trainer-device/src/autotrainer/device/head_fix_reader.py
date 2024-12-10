from __future__ import annotations

import os
import logging
import time
from datetime import datetime
from queue import Queue
from threading import Timer
from typing import Callable, Optional

import numpy

from autotrainer.core.project import ProjectInfo, ProjectInterval
from autotrainer.core import PerfMonitor, ObservableObject, EventManager

from .device_reader import DeviceReader
from .head_fix import HeadFixMessageKind
from .head_fix_event_kind import HeadFixEventKind

logger = logging.getLogger(__name__)

_NO_OP_TIMER = Timer(1.0, lambda: None)


class LoadCellMonitor(ObservableObject):
    def __init__(self):
        super().__init__()

        self.threshold: float = 10.0
        self.threshold_duration: float = 0.25
        self.min_hold_duration: float = 5.0
        self.post_hold_duration: float = 2.0

        self._last_active_start: int = 0
        self._was_active: bool = False
        self._active_debounce: Timer = _NO_OP_TIMER
        self._inactive_debounce: Timer = _NO_OP_TIMER
        self._when = 0
        self._index = 0

        self._is_engaged: bool = False

    @property
    def is_engaged(self) -> bool:
        return self._is_engaged

    def update(self, value: numpy.floating, when: int, index: int):
        if value > self.threshold:
            self._inactive_debounce.cancel()
            if not self._was_active:
                self._was_active = True
                self._when = when
                self._index = index
                self._active_debounce = Timer(self.threshold_duration, self._ensure_active)
                self._active_debounce.start()
        else:
            self._active_debounce.cancel()
            if self._was_active:
                self._was_active = False
                self._when = when
                self._index = index
                hold_time = time.perf_counter() - self._last_active_start
                if hold_time >= self.min_hold_duration:
                    duration = self.post_hold_duration
                else:
                    duration = max(self.post_hold_duration, self.min_hold_duration - hold_time)
                self._inactive_debounce = Timer(duration, self._ensure_inactive)
                self._inactive_debounce.start()

    def _ensure_active(self):
        if not self._is_engaged:
            self._is_engaged = True
            EventManager.instance().post_event(HeadFixEventKind.loadCellStateChanged, context=True,
                                               when=datetime.fromtimestamp(self._when), index=self._index)
            self.property_changed("is_engaged", True, False)

            self._last_active_start = time.perf_counter()

    def _ensure_inactive(self):
        if self._is_engaged:
            self._is_engaged = False
            EventManager.instance().post_event(HeadFixEventKind.loadCellStateChanged, context=False,
                                               when=datetime.fromtimestamp(self._when), index=self._index)
            self.property_changed("is_engaged", False, True)


class ForceDetector:
    def __init__(self):
        self._threshold: float = 400.0
        self._average_duration: float = 1.0
        self._sample_rate = 100

        self._values = numpy.empty((1, 0))

        self._weight = 0

        self._retain_count = round(self._sample_rate * self._average_duration)

    def update(self, values: list) -> bool:
        self._values = numpy.append(self._values, values)
        self._values = self._values[-self._retain_count:]

        self._weight = numpy.mean(self._values)

        return self._weight >= self._threshold


class TareDetector:
    def __init__(self):
        self._threshold: float = 0.1
        self._range_threshold: float = 0.2
        self._duration: float = 2.0
        self._sample_rate: int = 100

        self._buffer_len = int(self._sample_rate * self._duration)
        self._values = numpy.zeros(self._buffer_len)
        self._index = 0

    def update(self, values: list) -> bool:
        increase = len(values)

        self._values[self._index:(self._index + increase)] = numpy.array(values)

        self._index += increase

        if self._index >= self._buffer_len:
            self._index = 0

        r_max = numpy.max(self._values)
        r_min = numpy.min(self._values)

        return numpy.all(numpy.abs(self._values) > 0.1) and ((r_max - r_min) <= 0.2)


class HeadFixReader(DeviceReader):
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
        self._force_detector = ForceDetector()

        self._tare_detector = TareDetector()
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
    def load_cell_monitor(self):
        return self._load_cell_monitor

    def message_received(self, msg, data):
        if msg == HeadFixMessageKind.STREAM_START:
            self._perf_monitor.reset()
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
                                                                        self._force_detector.update(pressure),
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
