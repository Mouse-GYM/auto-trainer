import time
from dataclasses import dataclass
from datetime import datetime
from threading import Timer
from typing_extensions import Self

import yaml
import numpy

from ..observable_object import ObservableObject
from ..event_manager import EventManager

from .analysis_measurement_event_kind import AnalysisMeasurementEventKind

_NO_OP_TIMER = Timer(1.0, lambda: None)


@dataclass
class LoadCellConfiguration:
    threshold: float = 15.0
    threshold_duration: float = 0.25
    min_event_duration: float = 5.0
    min_post_event_hold_duration: float = 2.0

    @classmethod
    def from_version_zero(cls, content: dict) -> Self:
        return cls(
            threshold=content.get("load_trigger", 15),
            threshold_duration=content.get("min_load_on_duration", 0.25),
            min_event_duration=content.get("min_event_duration", 5.0),
            min_post_event_hold_duration=content.get("min_load_off_duration", 2.0)
        )


def load_cell_configuration_representer(dumper: yaml.SafeDumper, c: LoadCellConfiguration) -> yaml.nodes.MappingNode:
    return dumper.represent_mapping("!LoadCellConfiguration", {
        "threshold": c.threshold,
        "thresholdDuration": c.threshold_duration,
        "minEventDuration": c.min_event_duration,
        "minPostEventHoldDuration": c.min_post_event_hold_duration
    })


class LoadCellMonitor(ObservableObject):
    """
    Monitor the load cell data stream and perform any required analysis.  The current implementation is used to
    determine when the animal is in the tunnel.  At this time, this is specifically used downstream as a factor in
    whether to start and stop "sessions" of an experiment.
    """

    THRESHOLD_PROPERTY = "threshold"
    IS_ENGAGED_PROPERTY = "is_engaged"

    def __init__(self):
        super().__init__()

        self._threshold: float = 10.0
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
    def threshold(self) -> float:
        return self._threshold

    @threshold.setter
    def threshold(self, value: float):
        self._threshold = self._on_property_changed(LoadCellMonitor.THRESHOLD_PROPERTY, value, self._threshold)

    @property
    def is_engaged(self) -> bool:
        return self._is_engaged

    def load_configuration(self, configuration: LoadCellConfiguration):
        self.threshold = configuration.threshold
        self.threshold_duration = configuration.threshold_duration
        self.min_hold_duration = configuration.min_event_duration
        self.post_hold_duration = configuration.min_post_event_hold_duration

    def save_configuration(self) -> LoadCellConfiguration:
        return LoadCellConfiguration(
            threshold=self.threshold,
            threshold_duration=self.threshold_duration,
            min_event_duration=self.min_hold_duration,
            min_post_event_hold_duration=self.post_hold_duration
        )

    def update(self, value: numpy.floating, when: float, index: int):
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
            EventManager.post_event(AnalysisMeasurementEventKind.loadCellEngagedChanged, context=True,
                                    when=datetime.fromtimestamp(self._when), index=self._index)
            self.property_changed(LoadCellMonitor.IS_ENGAGED_PROPERTY, True, False)

            self._last_active_start = time.perf_counter()

    def _ensure_inactive(self):
        if self._is_engaged:
            self._is_engaged = False
            EventManager.post_event(AnalysisMeasurementEventKind.loadCellEngagedChanged, context=False,
                                    when=datetime.fromtimestamp(self._when), index=self._index)
            self.property_changed(LoadCellMonitor.IS_ENGAGED_PROPERTY, False, True)

    def force_engaged(self, engaged: bool) -> None:
        """
        Primarily used for testing.  This will force the load cell monitor to be engaged or not engaged.
        """
        if engaged != self._is_engaged:
            self._is_engaged = engaged
            self.property_changed(LoadCellMonitor.IS_ENGAGED_PROPERTY, self._is_engaged, not self._is_engaged)
            EventManager.post_event(AnalysisMeasurementEventKind.loadCellEngagedChanged,
                                    context=self._is_engaged, when=datetime.fromtimestamp(time.time()),
                                    index=time.perf_counter_ns())
