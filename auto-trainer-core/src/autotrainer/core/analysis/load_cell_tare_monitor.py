from __future__ import annotations

import numpy


class LoadCellTareMonitor:
    """
    Monitor the load cell data stream and whether zeroing is required.  The decision to actually zero or not is not
    performed here.  It simply reports whether the conditions meet the requirements where zeroing is applicable.
    """
    def __init__(self):
        self._threshold: float = 0.1
        self._range_threshold: float = 0.5
        self._duration: float = 2.0
        self._sample_rate: int = 100

        self._buffer_len = 0
        self._values = None
        self._index = 0

        self._reset()

    @property
    def threshold(self) -> float:
        return self._threshold

    @threshold.setter
    def threshold(self, value: float) -> None:
        self._threshold = value

    @property
    def range_threshold(self) -> float:
        return self._range_threshold

    @range_threshold.setter
    def range_threshold(self, value: float) -> None:
        self._range_threshold = value

    @property
    def duration(self) -> float:
        return self._duration

    @duration.setter
    def duration(self, value: float) -> None:
        self._duration = value
        self._reset()

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @sample_rate.setter
    def sample_rate(self, value: int) -> None:
        self._sample_rate = value
        self._reset()

    def update(self, values: list) -> bool:
        increase = len(values)

        self._values[self._index:(self._index + increase)] = numpy.array(values)

        self._index += increase

        if self._index >= self._buffer_len:
            self._index = 0

        return numpy.all(numpy.abs(self._values) > self._threshold) and numpy.ptp(self._values) <= self._range_threshold

    def _reset(self) -> None:
        self._buffer_len = int(self._sample_rate * self._duration)
        self._values = numpy.zeros(self._buffer_len)
        self._index = 0
