from __future__ import annotations

import time
from datetime import datetime
from threading import Timer

import numpy

from ..observable_object import ObservableObject
from ..event_manager import EventManager

from .analysis_measurement_event_kind import AnalysisMeasurementEventKind

_NO_OP_TIMER = Timer(1.0, lambda: None)


class LoadCellMonitor(ObservableObject):
    """
    Monitor the load cell data stream and perform any required analysis.  The current implementation is used to
    determine when the animal is in the tunnel.  At this time, this is specifically used downstream as a factor in
    whether to start and stop "sessions" of an experiment.
    """
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
            self.property_changed("is_engaged", True, False)

            self._last_active_start = time.perf_counter()

    def _ensure_inactive(self):
        if self._is_engaged:
            self._is_engaged = False
            EventManager.post_event(AnalysisMeasurementEventKind.loadCellEngagedChanged, context=False,
                                    when=datetime.fromtimestamp(self._when), index=self._index)
            self.property_changed("is_engaged", False, True)
