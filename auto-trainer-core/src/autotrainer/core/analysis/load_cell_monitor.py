import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from threading import Timer
from typing import Callable, List, Tuple, Deque, Optional, Union

from typing_extensions import Self

import yaml
import numpy

from autotrainer.core.logging import get_verbose_logger
from ..observable_object import ObservableObject
from ..event import EventManager

from .analysis_measurement_event_kind import AnalysisMeasurementEventKind


logger = get_verbose_logger(__name__)

_NO_OP_TIMER = Timer(1.0, lambda: None)


# to allow to be patched from tests:
_timer_load_cell_engaged = Timer



@dataclass
class LoadCellConfiguration:
    weight_active_threshold: float = 10  # grams
    weight_inactive_threshold: float = 3  # grams
    threshold_duration: float = 0.25  # duration threshold for active
    min_event_duration: float = 2.0
    min_post_event_hold_duration: float = 2.0

    thrashing_var_weight_threshold: float = 18   # grams
    thrashing_var_min_delay: float = 0.06  # seconds
    thrashing_var_max_delay: float = 0.18  # seconds
    thrashing_min_ptp_change_count: int = 2  # nbr of "ptp" change needed

    @classmethod
    def from_version_zero(cls, content: dict) -> Self:
        return cls(
            weight_active_threshold=content.get("load_trigger", 15),
            threshold_duration=content.get("min_load_on_duration", 0.25),
            min_event_duration=content.get("min_event_duration", 5.0),
            min_post_event_hold_duration=content.get("min_load_off_duration", 2.0),
        )


def load_cell_configuration_representer(dumper: yaml.SafeDumper, cfg: LoadCellConfiguration) -> yaml.nodes.MappingNode:

    return dumper.represent_mapping("!LoadCellConfiguration", {
        "weight_active_threshold": cfg.weight_active_threshold,
        "thresholdDuration": cfg.threshold_duration,
        "minEventDuration": cfg.min_event_duration,
        "minPostEventHoldDuration": cfg.min_post_event_hold_duration,
        "thrashing_var_weight_threshold": cfg.thrashing_var_weight_threshold,
        "thrashing_var_min_delay": cfg.thrashing_var_min_delay,
        "thrashing_var_max_delay": cfg.thrashing_var_max_delay,
        "thrashing_min_ptp_change_count": cfg.thrashing_min_ptp_change_count,
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
        config: Optional[LoadCellConfiguration] = None
        ):
        super().__init__()
        if config is None:
            config = LoadCellConfiguration()
        self._config = config
        #
        # self._load_cell_engaged_threshold: float = 10.0
        # self.threshold_duration: float = 0.25

        self._last_active_start: float = 0
        self._was_active: bool = False
        self._t_start_was_active: Optional[float] = None
        self._t_inactive_start = 0
        self._cur_ptp_count = 0
        self._t_last_ptp_check = 0
        self._active_debounce: Timer = _NO_OP_TIMER
        self._inactive_debounce: Timer = _NO_OP_TIMER
        self._when = 0
        self._index = 0
        self._is_engaged: bool = False
        self._t_next_hist_log = time.time()

        self._values_history: Deque[
            Tuple[float, float, int]
            # data, when, index
        ] = deque()
        self._thrashing_detected: bool = False

    @property
    def load_cell_engaged_threshold(self) -> float:
        return self._config.weight_active_threshold

    @load_cell_engaged_threshold.setter
    def load_cell_engaged_threshold(self, value: float):
        self._config.weight_active_threshold = self._on_property_changed(
            LoadCellMonitor.LOAD_CELL_ENGAGED_THRESHOLD_PROPERTY, value, self._config.weight_active_threshold)

    @property
    def is_engaged(self) -> bool:
        return self._is_engaged

    @property
    def thrashing_detected(self) -> bool:
        return self._thrashing_detected

    @thrashing_detected.setter
    def thrashing_detected(self, value):
        self._thrashing_detected = self._on_property_changed(
            self.IS_THRASHING_DETECTED_PROPERTY, value, self._thrashing_detected)

    @property
    def thrashing_var_minimum_delay(self) -> float:
        return self._config.thrashing_var_min_delay

    @thrashing_var_minimum_delay.setter
    def thrashing_var_minimum_delay(self, value):
        self._config.thrashing_var_min_delay = value

    @property
    def thrashing_var_weight_threshold(self) -> float:
        return self._config.thrashing_var_weight_threshold

    @thrashing_var_weight_threshold.setter
    def thrashing_var_weight_threshold(self, value):
        self._config.thrashing_var_min_delay = value

    def load_configuration(self, configuration: LoadCellConfiguration):
        self.load_cell_engaged_threshold = configuration.weight_active_threshold
        self._config = configuration

    def save_configuration(self) -> LoadCellConfiguration:
        return self._config

    def _update_history(self, value, when, index):
        hist = self._values_history
        cfg = self._config
        keep = max(
            cfg.threshold_duration,
            cfg.min_event_duration,
            cfg.min_post_event_hold_duration,
            cfg.thrashing_var_min_delay,
        )
        while len(hist) > 0:
            h0_when = hist[0][1]
            if when - h0_when <= keep:
                break
            hist.popleft()
        hist.append((value, when, index))

    def update(self, value: Union[float, numpy.floating], when: float, index: int):
        self._update_history(value, when, index)
        cfg = self._config
        t_start = self._t_start_was_active
        cur_engaged = self._is_engaged
        cur_thrashing = self._thrashing_detected
        hist = self._values_history
        if __debug__:
            t_now = time.time()
            if t_now > self._t_next_hist_log:
                logger.verbose("hist size=%s value=%.1f index=%s start_active=%s engaged=%s was_active=%s trashing=%s",
                               len(hist), value, index, t_start, cur_engaged, self._was_active, cur_thrashing)
                self._t_next_hist_log += 60
        # was not there:
        self._when = when
        self._index = index
        # reconsider.
        value = numpy.mean([v for v, w, _ in self._values_history if when - w < cfg.threshold_duration])
        if value >= cfg.weight_active_threshold:
            self._inactive_debounce.cancel()
            self._t_inactive_start = None
            t_start = self._t_start_was_active
            if t_start is None:
                self._was_active = True
                self._cur_ptp_count = 0
                self._t_inactive_start = None
                self._t_start_was_active = when
                self._active_debounce = _timer_load_cell_engaged(cfg.threshold_duration, self._ensure_active)
                self._active_debounce.start()
            else:
                if when - self._t_start_was_active > cfg.threshold_duration:
                    self._ensure_active()
                if self._cur_ptp_count == 0 or when - self._t_last_ptp_check >= cfg.thrashing_var_min_delay:
                    self._t_last_ptp_check = when
                    # consider ptp between now/when and cfg.thrashing_var_min_delay,
                    # and ptp between cfg.thrashing_var_min_delay and cfg.thrashing_var_max_delay
                    ptp_value1 = numpy.ptp([
                        h_val
                        for h_val, h_when, _ in self._values_history
                        if cfg.thrashing_var_min_delay <= when - h_when < cfg.thrashing_var_max_delay
                    ])
                    new_detected1 = bool(
                        # NB: using bool() given value is numpy.bool_ otherwise,
                        # we want to use native python bool instead, so the bool().
                        ptp_value1 >= cfg.thrashing_var_weight_threshold
                    )
                    delay2 = cfg.thrashing_var_min_delay
                    ptp_value2 = numpy.ptp([v for v, w, _ in self._values_history if when - w < delay2])
                    new_detected2 = bool(ptp_value2 >= cfg.thrashing_var_weight_threshold)
                    prev_detected = self._thrashing_detected
                    if new_detected1 or new_detected2:
                        self._cur_ptp_count += 1
                        if self._cur_ptp_count >= cfg.thrashing_min_ptp_change_count:
                            self.thrashing_detected = True
                    else:
                        self._cur_ptp_count = 0
                        # if when - self._t_last_ptp_check >= cfg.threshold_duration:
                        self.thrashing_detected = False
        else:
            if value < cfg.weight_inactive_threshold:
                self._active_debounce.cancel()
                hold_time = when - self._last_active_start
                if hold_time >= cfg.min_event_duration:
                    duration = cfg.min_post_event_hold_duration
                else:
                    duration = max(cfg.min_post_event_hold_duration, cfg.min_event_duration - hold_time)
                if self._t_inactive_start is None:
                    self._was_active = False
                    self._t_inactive_start = when
                    self._inactive_debounce = _timer_load_cell_engaged(duration, self._ensure_inactive)
                    self._inactive_debounce.start()
                if when - self._t_inactive_start > duration:
                    self._ensure_inactive()

    def _ensure_active(self):
        if self._is_engaged:
            return
        self._is_engaged = True
        EventManager.default().post_event_content(AnalysisMeasurementEventKind.loadCellEngagedChanged, context=True,
                                                  when=datetime.fromtimestamp(self._when), index=self._index)
        self.property_changed(LoadCellMonitor.IS_ENGAGED_PROPERTY, True, False)
        self._last_active_start = self._when

    def _ensure_inactive(self):
        if not self._is_engaged:
            return
        self._is_engaged = False
        self._was_active = False
        self._t_start_was_active = None
        self._cur_ptp_count = 0
        self.thrashing_detected = False
        self.property_changed(LoadCellMonitor.IS_ENGAGED_PROPERTY, False, True)
        EventManager.default().post_event_content(AnalysisMeasurementEventKind.loadCellEngagedChanged, context=False,
                                                  when=datetime.fromtimestamp(self._when), index=self._index)

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
