import itertools
import math
import time
import threading

import dataclasses
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Tuple, Deque, Optional, Union, Any, Dict

from typing_extensions import Self

import numpy

from autotrainer.core.logging import get_verbose_logger
from .. import build_kwargs_apply_mapping, make_camelize_representer
from ..multiproc import make_daemon_timer, no_op_timer
from ..observable_object import ObservableObject
from ..event import EventManager, ApiEventKind

logger = get_verbose_logger(__name__)

# to allow to be patched from tests:
_timer_load_cell_engaged = make_daemon_timer


@dataclass
class LoadCellConfiguration:
    # NB: this is the current/previous value used on agx001:
    weight_active_threshold: float = 2  # grams ; if above then will become engaged if above for threshold_duration
    weight_inactive_threshold: float = 2  # grams ;
    # if below then will become disengaged if below for more than

    threshold_duration: float = 0.25
    # duration threshold for engaged or thrashing_detected, must remain during that delay to make the change

    min_event_duration: float = 5.0
    min_post_event_hold_duration: float = 2.0
    # delay before inactive if was engaged/active for more than min_event_duration

    thrashing_var_weight_threshold_min: float = 20  # grams
    thrashing_var_weight_threshold_max: float = 30  # grams
    thrashing_var_min_delay: float = 0.05  # seconds
    thrashing_var_max_delay: float = 0.2  # seconds
    thrashing_min_ptp_change_count: int = 3  # nbr of "ptp" change needed in a row during var_max_delay

    @classmethod
    def from_version_zero(cls, content: Dict[str, Any]) -> Self:
        return cls(**build_kwargs_apply_mapping(content, (
            ('weight_active_threshold', 'load_trigger'),
            ('threshold_duration', 'min_load_on_duration'),
            ('min_post_event_hold_duration', 'min_load_off_duration'),
        )))

    @classmethod
    def from_version_one(cls, content: Dict[str, Any]) -> Self:
        return cls(**build_kwargs_apply_mapping(content, (
            ('weight_active_threshold', 'threshold'),
        )))


load_cell_configuration_representer = make_camelize_representer("!LoadCellConfiguration")


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
        """current if is currently engaged, or previous otherwise, engaged age"""
        return (time.perf_counter() if self.is_engaged else self.last_disengaged_perf_c) - self.last_engaged_perf_c

    @property
    def disengaged_age(self):
        # current or previous disengaged age
        return (time.perf_counter() if not self.is_engaged else self.last_engaged_perf_c) - self.last_disengaged_perf_c

    @property
    def thrashing_engaged_age(self):
        """current if it is currently detected, or previous otherwise thrashing_engaged_age"""
        return (time.perf_counter() if self.thrashing_detected else self.thrashing_last_disengaged_perf_c) - self.thrashing_last_engaged_perf_c

    @property
    def thrashing_disengaged_age(self):
        return (
            time.perf_counter() if not self.thrashing_detected else self.thrashing_last_engaged_perf_c) - self.thrashing_last_disengaged_perf_c


class LoadCellMonitor(ObservableObject):
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
        if config is None:
            config = LoadCellConfiguration()
        self._config = config
        self._last_engaged_start: float = 0
        self._cur_idx = 0
        self._t_start_was_active: Optional[float] = None
        self._t_inactive_start: Optional[float] = None
        self._cur_ptp_count = 0
        self._t_last_ptp_check = 0
        self._active_debounce = no_op_timer
        self._inactive_debounce = no_op_timer
        self._when = 0  # used to pass with event when engaged is changed
        self._index = 0  # used to pass with event when engaged is changed
        self._force_engaged: bool = False  # debug
        self._engaged_batch_count: int = 10  # how many last values to use as mean for check is_engaged
        # same than in HardwareModel.connect (currently hardcoded too)
        self._t_next_hist_log = time.time()
        self._values_history: Deque[
            Tuple[float, float, int]
            # data, when, index
        ] = deque()
        perf_now = time.perf_counter()
        self._thread_lock = threading.RLock()  # might be required re-entrant lock !!
        self._context = LoadCellMonitorContext(
            last_engaged_perf_c=perf_now,
            last_disengaged_perf_c=perf_now,
            thrashing_last_engaged_perf_c=perf_now,
            thrashing_last_disengaged_perf_c=perf_now,
        )

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
        self._config.weight_active_threshold = self._on_property_changed(
            LoadCellMonitor.LOAD_CELL_ENGAGED_THRESHOLD_PROPERTY, value, self._config.weight_active_threshold)

    @property
    def is_engaged(self) -> bool:
        return self._context.is_engaged

    @is_engaged.setter
    def is_engaged(self, value):
        with self._thread_lock:
            if value == self._context.is_engaged:
                return
            new_context = dataclasses.replace(self._context, is_engaged=value)
            perf_now = time.perf_counter()
            if value:
                new_context.last_engaged_perf_c = perf_now
            else:
                self._t_start_was_active = None
                new_context.last_disengaged_perf_c = perf_now
            self._context = new_context
            EventManager.default().post_event_content(ApiEventKind.loadCellEngagedChanged, context=value,
                                                      when=datetime.fromtimestamp(self._when), index=self._index)
            # could eventually execute the event without the lock acquired:
            self._on_property_changed(LoadCellMonitor.IS_ENGAGED_PROPERTY, value, not value)

    @property
    def thrashing_detected(self) -> bool:
        return self._context.thrashing_detected

    @thrashing_detected.setter
    def thrashing_detected(self, value):
        with self._thread_lock:
            self._set_thrashing_detected(value)

    def _set_thrashing_detected(self, value):
        ctx = self._context
        prev = ctx.thrashing_detected
        if value != prev:
            new_ctx = dataclasses.replace(ctx, thrashing_detected=value)
            logger.debug("load_cell_monitor.thrashing_detected=%s", value)
            perf_now = time.perf_counter()
            if value:
                new_ctx.thrashing_last_engaged_perf_c = perf_now
            else:
                new_ctx.thrashing_last_disengaged_perf_c = perf_now
            self._context = new_ctx
            self._on_property_changed(self.IS_THRASHING_DETECTED_PROPERTY, value, prev)

    def load_configuration(self, configuration: LoadCellConfiguration):
        # force the on_property_changed event too (if new value differs) :
        self.load_cell_engaged_threshold = configuration.weight_active_threshold
        # before resetting the new config:
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
        while len(hist) > 0 and len(hist) >= self._engaged_batch_count:
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

    def _make_thrashing_check(self, when, cfg):
        if not (
                self.is_engaged
                and when - self._t_last_ptp_check >= cfg.thrashing_var_min_delay
        ):
            return
        self._t_last_ptp_check = when
        # consider ptp between when and cfg.thrashing_var_min_delay,
        # and ptp between when and cfg.thrashing_var_max_delay
        detected1 = self._check_ptp_threshold(
            when, 0, cfg.thrashing_var_min_delay, cfg.thrashing_var_weight_threshold_min)
        detected2 = self._check_ptp_threshold(
            when, 0, cfg.thrashing_var_max_delay, cfg.thrashing_var_weight_threshold_max)
        if (detected1 and detected2) or ((detected1 or detected2) and self._cur_ptp_count > 0):
            self._cur_ptp_count += 1 if detected1 != detected2 else 1.5
            if self._cur_ptp_count >= cfg.thrashing_min_ptp_change_count:
                self.thrashing_detected = True
                self._cur_ptp_count = 0
                # to makes longer thrashing period we could only keep it on min_ptp_change_count value,
                # and rely on below logic
                self._t_last_ptp_check += cfg.thrashing_var_max_delay
                # otherwise thrashing ON period does not last very long.
            else:
                # put back next check
                self._t_last_ptp_check += cfg.thrashing_var_max_delay if detected1 and detected2 else (
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
                self._t_last_ptp_check += cfg.thrashing_var_max_delay if not (
                            detected1 or detected2) else cfg.thrashing_var_min_delay

    def update(self, value: Union[float, numpy.floating], when: float, index: int):
        if self._force_engaged:
            # debug code
            value = self._config.weight_active_threshold + 0.1
        self._update_history(value, when, index)
        cfg = self._config
        t_start = self._t_start_was_active
        ctx = self._context
        cur_engaged = ctx.is_engaged
        cur_thrashing = ctx.thrashing_detected
        if __debug__:
            t_now = time.time()
            if t_now > self._t_next_hist_log:
                logger.verbose("hist size=%s value=%.1f index=%s start_active=%s engaged=%s trashing=%s",
                               len(self._values_history), value, index, t_start, cur_engaged, cur_thrashing)
                self._t_next_hist_log += 60
        # always:
        self._make_thrashing_check(when, cfg)
        #
        self._cur_idx += 1
        if self._cur_idx >= self._engaged_batch_count:
            self._cur_idx = 0
            n_values = len(self._values_history)
            prev_n_values = [(v, w) for v, w, _ in itertools.islice(self._values_history,
                                                                    n_values - self._engaged_batch_count, n_values)]
            when = prev_n_values[0][1]  # using the first one when
            value = numpy.mean([prev[0] for prev in prev_n_values])
            if value >= cfg.weight_active_threshold:
                self._inactive_debounce.cancel()
                self._t_inactive_start = None
                if t_start is None:
                    self._when = when
                    self._index = index
                    self._t_start_was_active = when
                    self._cur_ptp_count = 0
                    logger.verbose("considering to engage within %.3f seconds", cfg.threshold_duration)
                    if self.use_timer:
                        self._active_debounce = _timer_load_cell_engaged(cfg.threshold_duration, self._ensure_active)
                        self._active_debounce.start()
                elif when - t_start > cfg.threshold_duration:
                    self._active_debounce.cancel()
                    self._ensure_active()

            elif value < cfg.weight_inactive_threshold:
                # inactive case
                self._active_debounce.cancel()
                self._t_start_was_active = None
                hold_time = when - self._last_engaged_start
                if hold_time >= cfg.min_event_duration:
                    duration = cfg.min_post_event_hold_duration
                else:
                    duration = max(cfg.min_post_event_hold_duration, cfg.min_event_duration - hold_time)
                if self._t_inactive_start is None:
                    logger.verbose("considering to disengage within %.3f seconds", duration)
                    self._t_inactive_start = when
                    self._index = index
                    if self.use_timer:
                        self._inactive_debounce = _timer_load_cell_engaged(duration, self._ensure_inactive)
                        self._inactive_debounce.start()
                elif when - self._t_inactive_start > duration:
                    self._inactive_debounce.cancel()
                    self._ensure_inactive()
            else:
                # inactive_threshold <= weight < active_threshold
                # in between, only cancel the inactive debounce
                self._inactive_debounce.cancel()
                self._t_inactive_start = None

    def _ensure_active(self):
        # can be called directly from caller of update() thread or indirectly with a timer thread
        # not sure if we should not maybe better only handle the direct one..
        with self._thread_lock:
            self.__ensure_active()

    def __ensure_active(self):
        if self.is_engaged:
            return
        logger.notice("Setting active / engaged ; prev weight: %s", self._values_history[-1])
        self._when = self._t_start_was_active
        self._last_engaged_start = self._t_start_was_active
        self._t_last_ptp_check = self._t_start_was_active + self._config.thrashing_var_max_delay
        self.is_engaged = True  # last on purpose

    def _ensure_inactive(self):
        # can be called directly from caller of update() thread or indirectly with a timer thread
        with self._thread_lock:
            self.__ensure_inactive()

    def __ensure_inactive(self):
        if not self.is_engaged:
            return
        logger.notice("Setting inactive / disengaged ; prev weight: %s", self._values_history[-1])
        self._when = self._t_inactive_start
        self._t_start_was_active = None
        self._cur_ptp_count = 0
        self.thrashing_detected = False
        self.is_engaged = False  # last

    def force_engaged(self, engaged: bool) -> None:
        """
        Primarily used for testing.  This will force the load cell monitor to be engaged or not engaged.
        """
        logger.verbose("Force engaged: %s", engaged)
        self._force_engaged = engaged
