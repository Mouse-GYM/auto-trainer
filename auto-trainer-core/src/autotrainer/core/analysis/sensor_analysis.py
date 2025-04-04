from __future__ import annotations

import os
import logging
import time
from datetime import datetime
from typing import Callable, Optional

import numpy

from autotrainer.core import ObservableObject, ProjectInfo, ProjectInterval, PerfMonitor, AudioSpectrumMessage
from .headbar_pressure_monitor import HeadbarPressureMonitor

from .load_cell_monitor import LoadCellMonitor
from .load_cell_tare_monitor import LoadCellTareMonitor

logger = logging.getLogger(__name__)


# TODO: Separate true analysis from data recording to file(s) for post-analysis.
class SensorAnalysis(ObservableObject):
    def __init__(self):
        super().__init__()

        self._project_info: Optional[ProjectInfo] = None
        self._interval = ProjectInterval.HOUR

        # The "monitor" CSV file with the bulk of the sensor data.
        self._record_file = None
        self._current_record_interval = -1
        self._had_write_error = False

        # The audio spectrum file.
        self._audio_record_file = None
        self._current_audio_record_interval = -1
        self._audio_had_write_error = False

        self._is_headbar_engaged = False

        self._is_load_cell_engaged = False
        self._load_cell_monitor = LoadCellMonitor()
        self._load_cell_monitor.property_changed += self._load_cell_property_changed

        self._is_force_detector_engaged = False
        self._force_detector = HeadbarPressureMonitor()

        self._tare_detector = LoadCellTareMonitor()
        self._tare_callback = None

        self._perf_monitor = PerfMonitor(name="<sensor-analysis>", units="mps", report_count=3000)

    @property
    def project_info(self) -> ProjectInfo:
        return self._project_info

    @project_info.setter
    def project_info(self, value: ProjectInfo) -> None:
        if self._record_file is not None:
            self._record_file.close()

        self._project_info = value
        self._update_record_file()
        self._update_audio_file()

        self._perf_monitor.reset()

    @property
    def interval(self) -> ProjectInterval:
        return self._interval

    @interval.setter
    def interval(self, value: ProjectInterval) -> None:
        self._interval = value

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

    def stream_start(self):
        self._perf_monitor.reset()

    def measurements_received(self, measurements):
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

        for m in measurements:
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
                        logger.error(f"<sensor-analysis>: unable to write: {e}")
                        self._had_write_error = True

        # Load cell monitor.
        self._load_cell_monitor.update(numpy.mean(weights), measurements[0].when, measurements[0].timestamp)

        # Headbar monitor.
        self._is_headbar_engaged = self._on_property_changed("is_headbar_engaged", numpy.mean(switch) > 0.5,
                                                             self._is_headbar_engaged)

        # Force detector.
        self._is_force_detector_engaged = self._on_property_changed("is_force_detector_engaged",
                                                                    self._force_detector.update(pressure,
                                                                                                measurements[0].when,
                                                                                                measurements[
                                                                                                    0].timestamp),
                                                                    self._is_force_detector_engaged)

        if self._tare_detector.update(weights) and self._tare_callback is not None:
            self._tare_callback()

        # Performance monitoring.
        self._perf_monitor.add_cycles(len(measurements))

        return weights, switch, pressure, temperature, humidity

    def audio_spectrum_received(self, spectrum: AudioSpectrumMessage):
        if spectrum is None or not spectrum.magnitudes:
            return

        if self._audio_record_file is not None:
            file_timestamp = datetime.now()

            needs_update = file_timestamp.hour != self._current_audio_record_interval \
                if self._interval == ProjectInterval.HOUR \
                else file_timestamp.minute != self._current_audio_record_interval

            if needs_update:
                self._update_audio_file()

        # May or may not exist after the above.
        if self._audio_record_file is not None:
            try:
                self._audio_record_file.write(f"{spectrum.when}, {spectrum.index}," +
                                              f"{','.join([str(s) for s in spectrum.magnitudes])}\n")
            except Exception as e:
                # This could be too much if something major is wrong.  Just output once per file rotation.
                if not self._audio_had_write_error:
                    logger.error(f"<sensor-analysis>: unable to write: {e}")
                    self._audio_had_write_error = True

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
                logger.error("<sensor-analysis>: unable to write to expected monitor file location")
                return

            try:
                file_existed = os.path.exists(interval_file_info.file)

                location = open(interval_file_info.file, "a")

                if not file_existed:
                    location.write("Time, Index, Weight, Switch, Pressure, Temperature, Humidity\n")

                self._current_record_interval = interval_file_info.current_interval
                self._record_file = location
                logger.info(f"<sensor-analysis>: saving to {interval_file_info.file}")
                self._had_write_error = False
            except:
                logger.error(f"<sensor-analysis>: unable to write to {interval_file_info.file}")

        return None

    def _update_audio_file(self) -> None:
        if self._audio_record_file is not None:
            try:
                self._audio_record_file.close()
            except:
                pass

            self._audio_record_file = None

        if self._project_info is not None:
            interval_file_info = self._project_info.get_audio_spectrum_file(interval=self._interval)

            if interval_file_info is None:
                logger.error("<sensor-analysis>: unable to write to expected audio file location")
                return

            try:
                file_existed = os.path.exists(interval_file_info.file)

                location = open(interval_file_info.file, "a")

                if not file_existed:
                    location.write(f"Time, Index, {','.join(['Bin ' + str(s) for s in range(32)])}\n")

                self._current_audio_record_interval = interval_file_info.current_interval
                self._audio_record_file = location
                logger.info(f"<sensor-analysis>: saving audio spectrum to {interval_file_info.file}")
                self._audio_had_write_error = False
            except:
                logger.error(f"<sensor-analysis>: unable to write to {interval_file_info.file}")

        return None
