import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from threading import Timer
from typing import Callable, List, Tuple, Deque, Optional, Union

from typing_extensions import Self

import yaml
import numpy

from ..observable_object import ObservableObject
from ..event import EventManager

from .analysis_measurement_event_kind import AnalysisMeasurementEventKind

_NO_OP_TIMER = Timer(1.0, lambda: None)


# to allow to be patched from tests:
_timer_load_cell_engaged = Timer



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

    LOAD_CELL_ENGAGED_THRESHOLD_PROPERTY = "load_cell_engaged_threshold"
    IS_ENGAGED_PROPERTY = "is_engaged"
    IS_THRASHING_DETECTED_PROPERTY = "is_thrashing_detected"

    def __init__(
        self,
        *,
        thrashing_var_weight_threshold: float = 25,  # g for grams
        thrashing_var_minimum_delay: float = 1,  # seconds
        ):
        super().__init__()

        self._load_cell_engaged_threshold: float = 10.0
        self.threshold_duration: float = 0.25
        self.min_hold_duration: float = 5.0
        self.post_hold_duration: float = 2.0

        self._last_active_start: int = 0
        self._was_active: bool = False
        self._t_start_was_active: Optional[float] = None
        self._active_debounce: Timer = _NO_OP_TIMER
        self._inactive_debounce: Timer = _NO_OP_TIMER
        self._when = 0
        self._index = 0
        self._is_engaged: bool = False

        self._thrashing_var_weight_threshold = thrashing_var_weight_threshold
        self._thrashing_var_minimum_delay = thrashing_var_minimum_delay
        self._values_history: Deque[
            Tuple[float, float, int]
            # data, when, index
        ] = deque()
        self._history_max_age: float = thrashing_var_minimum_delay  # seconds
        self._thrashing_detected: bool = False

    @property
    def load_cell_engaged_threshold(self) -> float:
        return self._load_cell_engaged_threshold

    @load_cell_engaged_threshold.setter
    def load_cell_engaged_threshold(self, value: float):
        self._load_cell_engaged_threshold = self._on_property_changed(LoadCellMonitor.LOAD_CELL_ENGAGED_THRESHOLD_PROPERTY, value, self._load_cell_engaged_threshold)

    @property
    def is_engaged(self) -> bool:
        return self._is_engaged

    @property
    def thrashing_detected(self) -> bool:
        return self._thrashing_detected

    @property
    def thrashing_var_minimum_delay(self) -> float:
        return self._thrashing_var_minimum_delay

    @thrashing_var_minimum_delay.setter
    def thrashing_var_minimum_delay(self, value):
        self._thrashing_var_minimum_delay = value

    @property
    def thrashing_var_weight_threshold(self) -> float:
        return self._thrashing_var_weight_threshold

    @thrashing_var_weight_threshold.setter
    def thrashing_var_weight_threshold(self, value):
        self._thrashing_var_minimum_delay = value

    def load_configuration(self, configuration: LoadCellConfiguration):
        self.load_cell_engaged_threshold = configuration.threshold
        self.threshold_duration = configuration.threshold_duration
        self.min_hold_duration = configuration.min_event_duration
        self.post_hold_duration = configuration.min_post_event_hold_duration

    def save_configuration(self) -> LoadCellConfiguration:
        return LoadCellConfiguration(
            threshold=self.load_cell_engaged_threshold,
            threshold_duration=self.threshold_duration,
            min_event_duration=self.min_hold_duration,
            min_post_event_hold_duration=self.post_hold_duration
        )

    def _update_history(self, value, when, index):
        hist = self._values_history
        while len(hist) > 0:
            h0_val, h0_when, h0_idx = hist[0]
            if when - h0_when <= self._history_max_age:
                break
            hist.popleft()
        hist.append((value, when, index))

    def update(self, value: float, when: float, index: int):
        self._update_history(value, when, index)
        t_start = self._t_start_was_active
        prev_detected = self._thrashing_detected
        if value > self.load_cell_engaged_threshold:
            self._inactive_debounce.cancel()
            if t_start is not None:
                if when - self._t_start_was_active > self._thrashing_var_minimum_delay:
                    ptp_value = numpy.ptp([
                        h_val
                        for h_val, h_when, _ in self._values_history
                        if when - h_when < self._thrashing_var_minimum_delay
                    ])
                    new_detected = bool(
                        # NB: using bool() given value is numpy.bool_ otherwise,
                        # we want to use native python bool instead, so the bool().
                        ptp_value >= self._thrashing_var_weight_threshold
                    )
                    self._thrashing_detected = self._on_property_changed(
                        self.IS_THRASHING_DETECTED_PROPERTY, new_detected, prev_detected)
            else:
                self._was_active = True
                self._t_start_was_active = when
                self._when = when
                self._index = index
                self._active_debounce = _timer_load_cell_engaged(self.threshold_duration, self._ensure_active)
                self._active_debounce.start()
        else:
            self._active_debounce.cancel()
            # not sure that we want this here:
            self._thrashing_detected = self._on_property_changed(self.IS_THRASHING_DETECTED_PROPERTY, False, prev_detected)
            #
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
            EventManager.default().post_event_content(AnalysisMeasurementEventKind.loadCellEngagedChanged, context=True,
                                                      when=datetime.fromtimestamp(self._when), index=self._index)
            self.property_changed(LoadCellMonitor.IS_ENGAGED_PROPERTY, True, False)

            self._last_active_start = time.perf_counter()

    def _ensure_inactive(self):
        if self._is_engaged:
            self._is_engaged = False
            EventManager.default().post_event_content(AnalysisMeasurementEventKind.loadCellEngagedChanged, context=False,
                                                      when=datetime.fromtimestamp(self._when), index=self._index)
            self.property_changed(LoadCellMonitor.IS_ENGAGED_PROPERTY, False, True)

    def force_engaged(self, engaged: bool) -> None:
        """
        Primarily used for testing.  This will force the load cell monitor to be engaged or not engaged.
        """
        if engaged != self._is_engaged:
            self._is_engaged = engaged
            self.property_changed(LoadCellMonitor.IS_ENGAGED_PROPERTY, self._is_engaged, not self._is_engaged)
            EventManager.default().post_event_content(AnalysisMeasurementEventKind.loadCellEngagedChanged,
                                                      context=self._is_engaged, when=datetime.fromtimestamp(time.time()),
                                                      index=time.perf_counter_ns())
