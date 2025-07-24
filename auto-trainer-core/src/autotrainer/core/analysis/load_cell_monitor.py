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
    weight_active_threshold: float = 15  # grams ; if above then will become engaged if above for threshold_duration
    weight_inactive_threshold: float = 5  # grams

    threshold_duration: float = 0.3
    # duration threshold for engaged or thrashing_detected, must remain during that delay to make the change

    min_event_duration: float = 2.0
    min_post_event_hold_duration: float = 2.0
    # delay before inactive if was engaged/active for more than min_event_duration

    thrashing_var_weight_threshold_min: float = 20   # grams
    thrashing_var_weight_threshold_max: float = 30   # grams
    thrashing_var_min_delay: float = 0.05  # seconds
    thrashing_var_max_delay: float = 0.2  # seconds
    thrashing_min_ptp_change_count: int = 3  # nbr of "ptp" change needed in a row during var_max_delay

    @classmethod
    def from_version_zero(cls, content: dict) -> Self:
        kwargs = {}
        def get_from_content(key, dest=None):
            if dest is None:
                dest = key
            if key in content:
                kwargs[dest] = content[key]

        get_from_content('load_trigger', 'weight_active_threshold')
        get_from_content('min_load_on_duration', 'threshold_duration')
        get_from_content('min_event_duration')
        get_from_content('min_load_off_duration', 'min_post_event_hold_duration')

        return cls(**kwargs)


def load_cell_configuration_representer(dumper: yaml.SafeDumper, cfg: LoadCellConfiguration) -> yaml.nodes.MappingNode:

    return dumper.represent_mapping("!LoadCellConfiguration", {
        "weight_active_threshold": cfg.weight_active_threshold,
        "thresholdDuration": cfg.threshold_duration,
        "minEventDuration": cfg.min_event_duration,
        "minPostEventHoldDuration": cfg.min_post_event_hold_duration,
        "thrashing_var_weight_threshold": cfg.thrashing_var_weight_threshold_min,
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
        self._last_engaged_start: float = 0
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
    def config(self) -> LoadCellConfiguration:
        return self._config

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

    @is_engaged.setter
    def is_engaged(self, value):
        if value != self._is_engaged:
            EventManager.default().post_event_content(AnalysisMeasurementEventKind.loadCellEngagedChanged, context=value,
                                                      when=datetime.fromtimestamp(self._when), index=self._index)
        self._is_engaged = self._on_property_changed(
            LoadCellMonitor.IS_ENGAGED_PROPERTY, value, self._is_engaged)

    @property
    def thrashing_detected(self) -> bool:
        return self._thrashing_detected

    @thrashing_detected.setter
    def thrashing_detected(self, value):
        self._when = self._t_last_ptp_check - self._config.thrashing_var_max_delay
        if value != self._thrashing_detected:
            logger.debug("load_cell_monitor.thrashing_detected=%s", value)
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
        return self._config.thrashing_var_weight_threshold_min

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
            cfg.thrashing_var_max_delay,
        )
        while len(hist) > 0:
            h0_when = hist[0][1]
            if when - h0_when <= keep:
                break
            hist.popleft()
        hist.append((value, when, index))

    def _check_ptp_threshold(self, cur_when: float, min_delay: float, max_delay: float, ptp_threshold: float):
        values = [
            h_val
            for h_val, h_when, _ in self._values_history
            if min_delay <= cur_when - h_when < max_delay
        ]
        ptp_value = numpy.ptp(values)
        if __debug__:
            if ptp_value >= ptp_threshold:
                logger.debug("ptp_value=%s threshold=%s", ptp_value, ptp_threshold)
        return bool(
            # NB: using bool() given value is numpy.bool_ otherwise,
            # we want to use native python bool instead, so the bool().
            ptp_value >= ptp_threshold
        ) if len(values) > 0 else False

    def _make_ptp_check(self, when, cfg):
        if not (
            self._is_engaged
            and when - self._t_last_ptp_check >= cfg.thrashing_var_min_delay
        ):
            return
        self._t_last_ptp_check = when
        # consider ptp between now/when and cfg.thrashing_var_min_delay,
        # and ptp between cfg.thrashing_var_min_delay and cfg.thrashing_var_max_delay
        detected1 = self._check_ptp_threshold(
            when, 0, cfg.thrashing_var_min_delay, cfg.thrashing_var_weight_threshold_min,
        )
        detected2 = self._check_ptp_threshold(
            when, 0, cfg.thrashing_var_max_delay, cfg.thrashing_var_weight_threshold_max)
        # self._t_last_ptp_check += cfg.thrashing_var_max_delay / cfg.thrashing_min_ptp_change_count
        if (detected1 and detected2) or ((detected1 or detected2) and self._cur_ptp_count > 0):
            self._cur_ptp_count += 1 if detected1 != detected2 else 1.5
            if self._cur_ptp_count >= cfg.thrashing_min_ptp_change_count:
                self.thrashing_detected = True
                self._cur_ptp_count = 0
            self._t_last_ptp_check += cfg.thrashing_var_max_delay if detected1 and detected2 else cfg.thrashing_var_min_delay
        else:
            if not detected1 and not detected2:
                self._cur_ptp_count = 0
            elif self._cur_ptp_count > 0:
                self._cur_ptp_count -= 1
            if self._cur_ptp_count <= 0:
                self.thrashing_detected = False
            self._t_last_ptp_check += cfg.thrashing_var_max_delay if self._cur_ptp_count < 0 else cfg.thrashing_var_min_delay


    def update(self, value: Union[float, numpy.floating], when: float, index: int):
        self._update_history(value, when, index)
        cfg = self._config
        t_start = self._t_start_was_active
        cur_engaged = self._is_engaged
        cur_thrashing = self._thrashing_detected
        if __debug__:
            t_now = time.time()
            if t_now > self._t_next_hist_log:
                logger.verbose("hist size=%s value=%.1f index=%s start_active=%s engaged=%s was_active=%s trashing=%s",
                               len(self._values_history), value, index, t_start, cur_engaged, self._was_active, cur_thrashing)
                self._t_next_hist_log += 60
        # value = numpy.mean([v for v, w, _ in self._values_history if when - w < cfg.threshold_duration])
        if value >= cfg.weight_active_threshold:
            self._inactive_debounce.cancel()
            if t_start is None:
                # self._when = when
                self._index = index
                self._was_active = True
                self._cur_ptp_count = 0
                self._t_inactive_start = None
                self._t_start_was_active = when
                self._active_debounce = _timer_load_cell_engaged(cfg.threshold_duration, self._ensure_active)
                self._active_debounce.start()
            else:
                if when - self._t_start_was_active > cfg.threshold_duration:
                    self._ensure_active()
                self._make_ptp_check(when, cfg)

        elif value < cfg.weight_inactive_threshold:
            # inactive case
            self._make_ptp_check(when, cfg)
            self._active_debounce.cancel()
            hold_time = when - self._last_engaged_start
            if hold_time >= cfg.min_event_duration:
                duration = cfg.min_post_event_hold_duration
            else:
                duration = max(cfg.min_post_event_hold_duration, cfg.min_event_duration - hold_time)
            if self._t_inactive_start is None:
                self._t_inactive_start = when
                self._inactive_debounce = _timer_load_cell_engaged(duration, self._ensure_inactive)
                self._inactive_debounce.start()
            elif when - self._t_inactive_start > duration:
                self._ensure_inactive()

        else:
            # in between
            self._make_ptp_check(when, cfg)
            self._inactive_debounce.cancel()
            self._t_inactive_start = None

    def _ensure_active(self):
        if self._is_engaged:
            return
        self._when = self._t_start_was_active
        self._last_engaged_start = self._t_start_was_active
        self._t_last_ptp_check = self._t_start_was_active + self._config.thrashing_var_max_delay
        self.is_engaged = True  # last on purpose

    def _ensure_inactive(self):
        if not self._is_engaged:
            return
        self._was_active = False
        self._when = self._t_inactive_start
        self._t_start_was_active = None
        self._cur_ptp_count = 0
        self.thrashing_detected = False
        self.is_engaged = False  # last

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
