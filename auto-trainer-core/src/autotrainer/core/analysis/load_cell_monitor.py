import itertools
import math

import dataclasses
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Tuple, Deque, Optional, Union

import numpy

from autotrainer.api import ApiDetectorKind, ApiEventKind

from autotrainer.core.logging import get_verbose_logger

from .detector import BaseDetector

from autotrainer.core import get_perf_now
from autotrainer.core.multiproc import make_daemon_timer, no_op_timer
from autotrainer.core.configuration.load_cell_config import LoadCellConfiguration
from autotrainer.core.event.event_manager import EventManager

logger = get_verbose_logger(__name__)

# to allow to be patched from tests:
_timer_load_cell_engaged = make_daemon_timer


@dataclass
class LoadCellMonitorContext:
    # using a dedicated "context" object, allows to have all attributes consistent, given we replace the active one
    # in the load cell monitor with new one having all needed attributes already replaced/set.
    # See LoadCellMonitor.is_engaged and LoadCellMonitor.thrashing_detected setters below.
    # This allows to get/read a consistent view/data of current/live context, *without* needing to take the thread lock.

    is_engaged: bool = False
    last_engaged_perf_c: float = -math.inf
    last_disengaged_perf_c: float = -math.inf

    thrashing_detected: bool = False
    thrashing_last_engaged_perf_c: float = -math.inf
    thrashing_last_disengaged_perf_c: float = -math.inf

    @property
    def engaged_age(self):
        """Current, if is currently engaged, or previous otherwise, engaged age"""
        return (get_perf_now() if self.is_engaged else self.last_disengaged_perf_c) - self.last_engaged_perf_c

    @property
    def disengaged_age(self):
        """Current or previous disengaged age"""
        return (get_perf_now() if not self.is_engaged else self.last_engaged_perf_c) - self.last_disengaged_perf_c

    @property
    def thrashing_engaged_age(self):
        """current if it is currently engaged, or previous otherwise thrashing_engaged_age"""
        age = get_perf_now() if self.thrashing_detected else self.thrashing_last_disengaged_perf_c
        return age - self.thrashing_last_engaged_perf_c

    @property
    def thrashing_disengaged_age(self):
        """current if it is currently disengaged, or previous otherwise thrashing_disengaged_age"""
        age = get_perf_now() if not self.thrashing_detected else self.thrashing_last_engaged_perf_c
        return age - self.thrashing_last_disengaged_perf_c


class LoadCellMonitor(BaseDetector):
    """
    Monitor the load cell data stream and perform any required analysis.  The current implementation is used to
    determine when the animal is in the tunnel.  At this time, this is specifically used downstream as a factor in
    whether to start and stop "sessions" of an experiment.
    """

    use_timer: bool = False
    # to use timer to allow triggering active/inactive, or not.

    LOAD_CELL_ENGAGED_THRESHOLD_PROPERTY = "load_cell_engaged_threshold"
    IS_ENGAGED_PROPERTY = "is_engaged"
    IS_THRASHING_DETECTED_PROPERTY = "is_thrashing_detected"

    def __init__(
        self,
        *,
        config: Optional[LoadCellConfiguration] = None
    ):
        super().__init__()
        self._config = LoadCellConfiguration() if config is None else config
        self._cur_idx = 0
        self._p_start_active = None  # get_perf_now()
        self._p_start_inactive = None  # get_perf_now()
        self._cur_ptp_count = 0
        self._p_last_ptp_check = 0
        self._active_debounce = no_op_timer
        self._inactive_debounce = no_op_timer
        self._index = 0  # used to pass with event when engaged is changed
        self._force_engaged: bool = False  # debug
        self._engaged_batch_count: int = 10  # how many last values to use as mean for check is_engaged
        # same than in HardwareModel.connect (currently hardcoded too)
        self._p_next_hist_log = get_perf_now()
        self._values_history: Deque[
            Tuple[float, float, float]
            # data, unix timestamp, perf_c
        ] = deque()
        self._context = LoadCellMonitorContext()

    def _check_state(self) -> Optional[float]:
        return None

    @property
    def context(self) -> LoadCellMonitorContext:
        return self._context

    @property
    def config(self) -> LoadCellConfiguration:
        return self._config

    @property
    def load_cell_engaged_threshold(self) -> float:
        return self._config.weight_active_threshold

    @load_cell_engaged_threshold.setter
    def load_cell_engaged_threshold(self, value: float):
        cfg = self._config
        prev, cfg.weight_active_threshold = cfg.weight_active_threshold, value
        self._on_property_changed(LoadCellMonitor.LOAD_CELL_ENGAGED_THRESHOLD_PROPERTY, value, prev)

    @property
    def is_engaged(self) -> bool:
        # overloading BaseDetector.is_engaged property on purpose, see LoadCellMonitorContext.
        return self._context.is_engaged

    @is_engaged.setter
    def is_engaged(self, is_engaged: bool):
        with self._lock:
            if is_engaged == self._context.is_engaged:
                return
            self._is_engaged = is_engaged  # keeps BaseDetector._is_engaged private synced
            new_context = dataclasses.replace(self._context, is_engaged=is_engaged)
            if is_engaged:
                related_perf_c = self._p_start_active
            else:
                related_perf_c = self._p_start_inactive
            if related_perf_c is None:
                related_perf_c = get_perf_now()
            if is_engaged:
                new_context.last_engaged_perf_c = related_perf_c
            else:
                new_context.last_disengaged_perf_c = related_perf_c
            self._context = new_context
        # executing the event without the lock acquired:
        logger.verbose("new context: %s", new_context)
        EventManager.default().post_event_content(
            ApiEventKind.loadCellEngagedChanged, data=dict(is_engaged=is_engaged),
            when=datetime.now() - timedelta(seconds=get_perf_now() - related_perf_c), index=self._index)
        self._on_property_changed(LoadCellMonitor.IS_ENGAGED_PROPERTY, is_engaged, not is_engaged)

    @property
    def thrashing_detected(self) -> bool:
        return self._context.thrashing_detected

    @thrashing_detected.setter
    def thrashing_detected(self, value):
        with self._lock:
            self._set_thrashing_detected(value)

    def _set_thrashing_detected(self, value):
        ctx = self._context
        prev = ctx.thrashing_detected
        if value == prev:
            return
        new_ctx = dataclasses.replace(ctx, thrashing_detected=value)
        logger.debug("load_cell_monitor.thrashing_detected=%s", value)
        perf_now = get_perf_now()
        if value:
            new_ctx.thrashing_last_engaged_perf_c = perf_now
        else:
            new_ctx.thrashing_last_disengaged_perf_c = perf_now
        self._context = new_ctx
        self.property_changed(self.IS_THRASHING_DETECTED_PROPERTY, value, prev)
        self.post_detector_event(ApiDetectorKind.loadCellThrash, value)

    def load_configuration(self, configuration: LoadCellConfiguration):
        # force the on_property_changed event too (if new value differs) :
        self.load_cell_engaged_threshold = configuration.weight_active_threshold
        # before resetting the new config:
        self._config = configuration

    def save_configuration(self) -> LoadCellConfiguration:
        return self._config

    def _update_history(self, value, when, perf_c):
        hist = self._values_history
        cfg = self._config
        keep = max(
            cfg.threshold_duration,
            cfg.min_event_duration,
            cfg.min_post_event_hold_duration,
            cfg.thrashing_var_min_delay,
            cfg.thrashing_var_max_delay,
        )
        while len(hist) > 0 and len(hist) >= self._engaged_batch_count:
            if perf_c - hist[0][2] <= keep:
                break
            hist.popleft()
        hist.append((value, when, perf_c))

    def _check_ptp_threshold(self, cur_perf_c: float, min_delay: float, max_delay: float, ptp_threshold: float):
        values = [
            h_val
            for h_val, _, h_perf_c in self._values_history
            if min_delay <= cur_perf_c - h_perf_c < max_delay
        ]
        if len(values) == 0:
            return False
        ptp_value = numpy.ptp(values)
        if __debug__:
            if ptp_value >= ptp_threshold:
                logger.debug("ptp_value=%s threshold=%s", ptp_value, ptp_threshold)
        return bool(
            # NB: using bool() given value is numpy.bool_ otherwise,
            # we want to use native python bool instead, so the bool().
            ptp_value >= ptp_threshold
        )

    def _make_thrashing_check(self, perf_c, cfg):
        if not (
            self.is_engaged
            and perf_c - self._p_last_ptp_check >= cfg.thrashing_var_min_delay
        ):
            return
        self._p_last_ptp_check = perf_c
        # consider ptp between when and cfg.thrashing_var_min_delay,
        # and ptp between when and cfg.thrashing_var_max_delay
        detected1 = self._check_ptp_threshold(
            perf_c, 0, cfg.thrashing_var_min_delay, cfg.thrashing_var_weight_threshold_min)
        detected2 = self._check_ptp_threshold(
            perf_c, 0, cfg.thrashing_var_max_delay, cfg.thrashing_var_weight_threshold_max)
        if (detected1 and detected2) or ((detected1 or detected2) and self._cur_ptp_count > 0):
            self._cur_ptp_count += 1 if detected1 != detected2 else 1.5
            if self._cur_ptp_count >= cfg.thrashing_min_ptp_change_count:
                self.thrashing_detected = True
                self._cur_ptp_count = 0
                # to makes longer thrashing period we could only keep it on min_ptp_change_count value,
                # and rely on below logic
                self._p_last_ptp_check += cfg.thrashing_var_max_delay
                # otherwise thrashing ON period does not last very long.
            else:
                # put back next check
                self._p_last_ptp_check += cfg.thrashing_var_max_delay if detected1 and detected2 else (
                cfg.thrashing_var_min_delay)
        else:
            # following might be adapted/changed
            if not detected1 and not detected2:
                self._cur_ptp_count = 0
                # to makes possible longer thrashing periods, we could subtract 1.5 like here instead.
            elif self._cur_ptp_count > 0:
                self._cur_ptp_count -= 1
            if self._cur_ptp_count <= 0:
                self.thrashing_detected = False
            else:
                self._p_last_ptp_check += cfg.thrashing_var_max_delay if not (
                            detected1 or detected2) else cfg.thrashing_var_min_delay

    def update(self, value: Union[float, numpy.floating], when: float, index: int):
        """
        value: weight in gram
        when: realtime UNIX timestamp
        index: nanosecond perf counter
        """
        cfg = self._config
        if self._force_engaged:
            # debug code
            value = self._config.weight_active_threshold + 0.1
        perf_c = index / 1e9
        self._update_history(value, when, perf_c)
        p_start = self._p_start_active
        ctx = self._context
        cur_engaged = ctx.is_engaged
        cur_thrashing = ctx.thrashing_detected
        if __debug__:
            p_now = get_perf_now()
            if p_now > self._p_next_hist_log:
                logger.verbose("hist size=%s value=%.1f index=%s start_active=%s engaged=%s trashing=%s",
                               len(self._values_history), value, index, p_start, cur_engaged, cur_thrashing)
                self._p_next_hist_log += 60
        # always:
        self._make_thrashing_check(perf_c, cfg)
        #
        self._cur_idx += 1
        if self._cur_idx >= self._engaged_batch_count:
            self._cur_idx = 0
            n_values = len(self._values_history)
            prev_n_values = [(v, p) for v, _, p in itertools.islice(self._values_history,
                                                                    n_values - self._engaged_batch_count, n_values)]
            value = numpy.mean([prev[0] for prev in prev_n_values])
            if value >= cfg.weight_active_threshold:
                self._inactive_debounce.cancel()
                self._p_start_inactive = None
                if p_start is None:
                    self._index = index
                    self._p_start_active = perf_c
                    self._cur_ptp_count = 0
                    logger.verbose("considering to engage within %.3f seconds", cfg.threshold_duration)
                    if self.use_timer:
                        self._active_debounce = _timer_load_cell_engaged(cfg.threshold_duration, self._ensure_active)
                        self._active_debounce.start()
                elif perf_c - p_start > cfg.threshold_duration:
                    self._active_debounce.cancel()
                    self._ensure_active()

            elif value < cfg.weight_inactive_threshold:
                # inactive case
                self._active_debounce.cancel()
                if cur_engaged:
                    hold_time = perf_c - self._p_start_active
                    if hold_time >= cfg.min_event_duration:
                        duration = cfg.min_post_event_hold_duration
                    else:
                        duration = max(cfg.min_post_event_hold_duration, cfg.min_event_duration - hold_time)
                else:
                    duration = 0
                if self._p_start_inactive is None:
                    logger.verbose("considering to disengage within %.3f seconds", duration)
                    self._p_start_inactive = perf_c
                    self._index = index
                    if self.use_timer:
                        self._inactive_debounce = _timer_load_cell_engaged(duration, self._ensure_inactive)
                        self._inactive_debounce.start()
                elif perf_c - self._p_start_inactive > duration:
                    self._inactive_debounce.cancel()
                    self._ensure_inactive()
            else:
                # inactive_threshold <= weight < active_threshold
                # in between, only cancel the inactive debounce
                self._inactive_debounce.cancel()
                self._p_start_inactive = None

    def _ensure_active(self):
        # can be called directly from caller of update() thread or indirectly with a timer thread
        # not sure if we should not maybe better only handle the direct one...
        with self._lock:
            self.__ensure_active()

    def __ensure_active(self):
        if self.is_engaged:
            return
        logger.notice("Setting active / engaged ; prev weight: %s", self._values_history[-1])
        self._p_last_ptp_check = self._p_start_active + self._config.thrashing_var_max_delay
        self.is_engaged = True  # last on purpose

    def _ensure_inactive(self):
        # can be called directly from caller of update() thread or indirectly with a timer thread
        with self._lock:
            self.__ensure_inactive()

    def __ensure_inactive(self):
        if not self.is_engaged:
            return
        logger.notice("Setting inactive / disengaged ; prev weight: %s", self._values_history[-1])
        self._p_start_active = None
        self._cur_ptp_count = 0
        self.thrashing_detected = False
        self.is_engaged = False  # last

    def force_engaged(self, engaged: bool) -> None:
        """
        Primarily used for testing.  This will force the load cell monitor to be engaged or not engaged.
        """
        logger.verbose("Force engaged: %s", engaged)
        self._force_engaged = engaged
        # self.is_engaged = engaged  # assuming the load-cell sensor is working and calling our .update() function
        # which will generate the engaged after the configured delay.
        # And same for disengage.
