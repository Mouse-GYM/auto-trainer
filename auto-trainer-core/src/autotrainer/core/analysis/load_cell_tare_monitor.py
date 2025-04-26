from dataclasses import dataclass
from typing import Callable, Optional

from typing_extensions import Self

import numpy
import yaml


@dataclass
class LoadCellAutoTareConfiguration:
    threshold: float = 0.1
    range_threshold: float = 0.75
    duration: float = 2.0

    @classmethod
    def from_version_zero(cls, content: dict) -> Self:
        return cls(
            threshold=content.get("threshold", 0.1),
            range_threshold=content.get("range_threshold", 0.75),
            duration=content.get("duration", 2.0)
        )


def load_cell_auto_tare_configuration_representer(dumper: yaml.SafeDumper,
                                                  c: LoadCellAutoTareConfiguration) -> yaml.nodes.MappingNode:
    return dumper.represent_mapping("!LoadCellAutoTareConfiguration", {
        "threshold": c.threshold,
        "rangeThreshold": c.range_threshold,
        "duration": c.duration
    })


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

        self._tare_callback: Optional[Callable[[], None]] = None

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

    @property
    def tare_callback(self):
        return self._tare_callback

    @tare_callback.setter
    def tare_callback(self, tare_callback: Callable[[], None]) -> None:
        self._tare_callback = tare_callback

    def load_configuration(self, configuration: LoadCellAutoTareConfiguration):
        self._threshold = configuration.threshold
        self._range_threshold = configuration.range_threshold
        self._duration = configuration.duration
        self._reset()

    def save_configuration(self) -> LoadCellAutoTareConfiguration:
        return LoadCellAutoTareConfiguration(
            threshold=self._threshold,
            range_threshold=self._range_threshold,
            duration=self._duration
        )

    def update(self, values: list) -> bool:
        # Currently there is no state management or other reason to perform the calculation if there is no callback.
        if not self._tare_callback:
            return False

        increase = len(values)

        self._values[self._index:(self._index + increase)] = numpy.array(values)

        self._index += increase

        if self._index >= self._buffer_len:
            self._index = 0

        if numpy.all(numpy.abs(self._values) > self._threshold) and numpy.ptp(self._values) <= self._range_threshold:
            self._tare_callback()
            return True

        return False

    def _reset(self) -> None:
        self._buffer_len = int(self._sample_rate * self._duration)
        self._values = numpy.zeros(self._buffer_len)
        self._index = 0
