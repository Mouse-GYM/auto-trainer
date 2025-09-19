from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Optional, List, Tuple

import numpy

from .head_fix_measurement import HeadFixMeasurement
from .audio_spectrum_monitor import AudioSpectrumThrashMonitor
from ..logging import get_verbose_logger
from ..project import ProjectInfo, ProjectInterval
from ..perf_monitor import PerfMonitor
from ..observable_object import ObservableObject
from ..message.audio_spectrum_message import AudioSpectrumMessage

from .headbar_pressure_monitor import HeadbarPressureMonitor
from .load_cell_monitor import LoadCellMonitor
from .load_cell_tare_monitor import LoadCellTareMonitor

logger = get_verbose_logger(__name__)


# small alias
_MeasuresList = List[float]


# TODO: Separate true analysis from data recording to file(s) for post-analysis.
class SensorAnalysis(ObservableObject):
    IS_HEADBAR_SWITCH_ENGAGED_PROPERTY = "is_headbar_switch_engaged"

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

        self._is_load_cell_engaged = False
        self._load_cell_monitor = LoadCellMonitor()

        # The analog pressure sensor on the headbar.
        self._is_headbar_pressure_engaged = False
        self._headbar_pressure_monitor = HeadbarPressureMonitor()

        # The digital i/o switch on the headbar.
        self._is_headbar_switch_engaged = False

        self._tare_detector = LoadCellTareMonitor()
        self._tare_callback = None

        self._audio_thrashing_monitor = AudioSpectrumThrashMonitor()

        self._perf_monitor = PerfMonitor(name="<sensor-analysis>", units="mps", report_window=30)

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
    def load_cell_monitor(self) -> LoadCellMonitor:
        return self._load_cell_monitor

    @property
    def headbar_pressure_monitor(self) -> HeadbarPressureMonitor:
        return self._headbar_pressure_monitor

    @property
    def load_cell_tare_monitor(self) -> LoadCellTareMonitor:
        return self._tare_detector

    @property
    def audio_thrashing_monitor(self) -> AudioSpectrumThrashMonitor:
        return self._audio_thrashing_monitor

    @property
    def is_headbar_switch_engaged(self):
        # TODO - this signal is not currently encapsulated in an object for whatever analysis is needed like the others.
        #  If it is used in the future, this should probably be refactored similar to the other sub-components.
        return self._is_headbar_switch_engaged

    def stream_start(self):
        logger.verbose("SensorAnalysis: stream_start")
        self._perf_monitor.reset()

    def measurements_received(
        self,
        measurements: List[HeadFixMeasurement]
    ) -> Tuple[_MeasuresList, _MeasuresList, _MeasuresList, _MeasuresList, _MeasuresList] :
        # logger.spam("Received %s measures", len(measurements))
        assert len(measurements) > 0
        weights: List[float] = []
        switch: List[float] = []
        pressure: List[float] = []
        temperature: List[float] = []
        humidity: List[float] = []

        if self._record_file is not None:
            now = datetime.now()

            needs_update = now.hour != self._current_record_interval \
                if self._interval == ProjectInterval.HOUR \
                else now.minute != self._current_record_interval

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
                        f"{m.when}, {m.timestamp}, {m.weight}, {m.switch}, {m.pressure}, "
                        f"{m.temperature}, {m.humidity}\n")
                except Exception as err:
                    # This could be too much if something major is wrong.  Just output once per file rotation.
                    if not self._had_write_error:
                        logger.exception("<sensor-analysis>: unable to write: %s", err)
                        self._had_write_error = True

        first_measure = measurements[0]
        # Load cell monitor.
        # self._load_cell_monitor.update(numpy.mean(weights), first_measure.when, first_measure.timestamp)
        for m in measurements:
            self._load_cell_monitor.update(m.weight, m.when, m.timestamp)

        # Headbar analog pressure monitor.
        self._headbar_pressure_monitor.update(pressure, first_measure.when, first_measure.timestamp)

        # Headbar digital switch - no real implementation at this time.
        self._is_headbar_switch_engaged = self._on_property_changed(SensorAnalysis.IS_HEADBAR_SWITCH_ENGAGED_PROPERTY,
                                                                    numpy.mean(switch) > 0.5,
                                                                    self._is_headbar_switch_engaged)

        # (Auto-)tare detection.
        self._tare_detector.update(weights)

        # Performance monitoring.
        self._perf_monitor.add_cycles(len(measurements))

        return weights, switch, pressure, temperature, humidity

    def audio_spectrum_received(self, spectrum: AudioSpectrumMessage):
        if spectrum is None or not spectrum.magnitudes:
            return

        self._audio_thrashing_monitor.update(spectrum.magnitudes, spectrum.when, spectrum.index)

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

    def _update_record_file(self) -> None:
        if self._record_file is not None:
            try:
                self._record_file.close()
            except Exception as err:
                logger.warning("Failure closing record file: %s", err)

            self._record_file = None

        if self._project_info is not None:
            interval_file_info = self._project_info.get_monitor_file(interval=self._interval, when=datetime.now())

            if interval_file_info is None:
                logger.error("<sensor-analysis>: unable to write to expected monitor file location")
                return None

            try:
                file_existed = os.path.exists(interval_file_info.file)

                location = open(interval_file_info.file, "a")

                if not file_existed:
                    location.write("Time, Index, Weight, Switch, Pressure, Temperature, Humidity\n")

                self._current_record_interval = interval_file_info.current_interval
                self._record_file = location
                logger.info(f"<sensor-analysis>: saving to {interval_file_info.file}")
                self._had_write_error = False
            except Exception as err:
                logger.error("<sensor-analysis>: unable to write to %s: %s",interval_file_info.file, err)

        return None

    def _update_audio_file(self) -> None:
        if self._audio_record_file is not None:
            try:
                self._audio_record_file.close()
            except Exception as err:
                logger.warning("audio record file close failed: %s", err)

            self._audio_record_file = None

        if self._project_info is not None:
            interval_file_info = self._project_info.get_audio_spectrum_file(
                interval=self._interval, when=datetime.now())

            if interval_file_info is None:
                logger.error("<sensor-analysis>: unable to write to expected audio file location")
                return None

            try:
                file_existed = os.path.exists(interval_file_info.file)

                location = open(interval_file_info.file, "a")

                if not file_existed:
                    location.write(f"Time, Index, {','.join(['Bin ' + str(s) for s in range(32)])}\n")

                self._current_audio_record_interval = interval_file_info.current_interval
                self._audio_record_file = location
                logger.info(f"<sensor-analysis>: saving audio spectrum to {interval_file_info.file}")
                self._audio_had_write_error = False
            except Exception as err:
                logger.error("<sensor-analysis>: unable to write to %r: %s", interval_file_info.file, err)

        return None
