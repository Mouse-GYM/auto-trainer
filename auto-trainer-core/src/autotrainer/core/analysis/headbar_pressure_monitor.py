import time
from dataclasses import dataclass
from math import floor
from datetime import datetime
from typing_extensions import Self

import yaml
import numpy

from .. import make_camelize_representer
from ..observable_object import ObservableObject
from ..event import EventManager

from .analysis_measurement_event_kind import AnalysisMeasurementEventKind


@dataclass
class HeadbarPressureConfiguration:
    threshold: float = 20
    duration: float = 0.5

    @classmethod
    def from_version_zero(cls, content: dict) -> Self:
        return cls(
            threshold=content.get("threshold", 30),
            duration=content.get("duration", 0.25)
        )


headbar_pressure_configuration_representer = make_camelize_representer("!HeadbarPressureConfiguration")


class HeadbarPressureMonitor(ObservableObject):
    """
    Monitor the headbar pressure data stream and perform any required analysis.  The current implementation is used to
    determine if the headbar is considered sufficiently "engaged" or not.  At this time, this is specifically used
    downstream to allow for the tunnel auto-clamp behavior, when enabled.
    """

    IS_ENGAGED_PROPERTY = "is_engaged"

    def __init__(self):
        super().__init__()

        self._sample_rate = 100

        self._load_cell_engaged_threshold: float = 30
        self._duration: float = 0.25

        self._values = numpy.empty((1, 0))

        self._buffer_length: float = 1.0
        self._retain_count: int = 1

        self._window_count: int = 3

        self._first_third = 1
        self._last_third = 1

        self._rebuild_buffers()

        self._is_engaged = False

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @sample_rate.setter
    def sample_rate(self, value: int) -> None:
        # Odd number sample rates lead to mismatched indexing.  Can just handle here once by effectively doing the
        # round.
        self._sample_rate = value + (value % 2)
        self._rebuild_buffers()

    @property
    def load_cell_engaged_threshold(self) -> float:
        return self._load_cell_engaged_threshold

    @load_cell_engaged_threshold.setter
    def load_cell_engaged_threshold(self, value: float) -> None:
        self._load_cell_engaged_threshold = self._on_property_changed("threshold", value, self._load_cell_engaged_threshold)

    @property
    def duration(self) -> float:
        return self._duration

    @duration.setter
    def duration(self, value: float) -> None:
        self._duration = self._on_property_changed("duration", value, self._duration)
        self._rebuild_buffers()

    @property
    def is_engaged(self) -> bool:
        return self._is_engaged

    def load_configuration(self, configuration: HeadbarPressureConfiguration):
        self.load_cell_engaged_threshold = configuration.threshold
        self.duration = configuration.duration

    def save_configuration(self) -> HeadbarPressureConfiguration:
        return HeadbarPressureConfiguration(threshold=self._load_cell_engaged_threshold, duration=self._duration)

    def update(self, values: list, when: float = 0.0, index: int = 0) -> bool:
        self._values = numpy.append(self._values, values)
        self._values = self._values[-self._retain_count:]

        if len(self._values) < self._retain_count:
            return False

        is_engaged = False

        # Values are appended and dropped in batches.  Need to evaluate over the full window size as more than just one
        # sample will be gone the next evaluation.  We could just evaluate oldest last window_count samples, but there
        # would be greater latency in the response.  We are also evaluating the same window of samples multiple times
        # depending on the measurement batch size, but this is simple calculation and not worth optimizing out at the
        # moment.
        for idx in range(self._window_count * 3):
            new_start = idx + self._last_third
            new_end = idx + self._window_count
            old_start = idx
            old_end = idx + self._first_third

            if numpy.all(self._values[old_start:old_end] <= (self._values[new_start:new_end] - self._load_cell_engaged_threshold)):
                is_engaged = True
                break

        if is_engaged != self._is_engaged:
            self._is_engaged = is_engaged
            self.property_changed(HeadbarPressureMonitor.IS_ENGAGED_PROPERTY, self._is_engaged, not self._is_engaged)
            EventManager.default().post_event_content(AnalysisMeasurementEventKind.headbarPressureEngagedChanged,
                                                      context=self._is_engaged,
                                                      when=datetime.fromtimestamp(when), index=index)
        self._is_engaged = is_engaged

        return is_engaged

    def _rebuild_buffers(self):
        # Measurements are received in batches.  Depending on that batch size, it may not result in a continuous, moving
        # evaluation with data processed in batches.  Store a larger buffer than the window so we can apply the window
        # over each starting and ending element.
        self._buffer_length = self._duration * 4
        self._retain_count = round(self._sample_rate * self._buffer_length)

        self._window_count = round(self._sample_rate * self._duration)

        self._first_third = floor(self._window_count / 3)
        self._last_third = self._window_count - self._first_third

    def force_engaged(self, engaged: bool) -> None:
        """
        Primarily used for testing.  This will force the headbar pressure monitor to be engaged or not engaged.
        """
        if engaged != self._is_engaged:
            self._is_engaged = engaged
            self.property_changed(HeadbarPressureMonitor.IS_ENGAGED_PROPERTY, self._is_engaged, not self._is_engaged)
            EventManager.default().post_event_content(AnalysisMeasurementEventKind.headbarPressureEngagedChanged,
                                                      context=self._is_engaged, when=datetime.fromtimestamp(time.time()),
                                                      index=time.perf_counter_ns())
