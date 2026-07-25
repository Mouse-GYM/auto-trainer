import datetime
import math
from datetime import timedelta
from typing import Optional

from autotrainer.core import get_perf_now, Offset3DTuple
from autotrainer.core.configuration.behavior_configuration import TimePeriod
from autotrainer.core.configuration.tunnel_sweep_config import AutoTunnelSweepConfiguration
from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.analysis.detector import BaseDetector
from autotrainer.core.analysis.pellet_position_monitor import PelletMisplacedDetector


logger = get_verbose_logger(__name__)


_offset_nans = Offset3DTuple(math.nan, math.nan, math.nan)


class AutoTunnelSweepMonitor(BaseDetector[AutoTunnelSweepConfiguration]):

    use_daemon = True
    default_timer_delay = 60  # for minute precision

    config_cls = AutoTunnelSweepConfiguration

    def __init__(
        self, *, pellet_misplaced_detector: PelletMisplacedDetector,
    ):
        super().__init__()
        self._misplaced_detector = pellet_misplaced_detector
        self._last_recurrent_perf_c = -math.inf
        self.animal_sleep_window = TimePeriod(start=datetime.time(0, 0), stop=datetime.time(0, 0))
        self._animal_in_training: bool = False
        pellet_misplaced_detector.property_changed += self._on_pellet_misplaced_property_changed

    @property
    def animal_in_training(self) -> bool:
        return self._animal_in_training

    @animal_in_training.setter
    def animal_in_training(self, value: bool):
        prev, self._animal_in_training = self._animal_in_training, value
        if value and value != prev:
            self._last_recurrent_perf_c = get_perf_now()
            self.check_state()

    def _start(self):
        super()._start()
        self._last_recurrent_perf_c = get_perf_now()

    def _stop(self):
        super()._stop()
        self.is_engaged = False  # force disengaged on stop

    def _check_state(self, *, force: bool=False) -> Optional[float]:
        cfg = self._config
        if not force and not cfg.enabled:
            return None
        p_now = get_perf_now()
        engaged = self._is_engaged
        if engaged:
            fan_on_remain = self.config.tunnel_fan_on_duration - (p_now - self._engaged_perf_c)
            if fan_on_remain > 0:
                return fan_on_remain
            self.is_engaged = False
            return None
        misplaced_det = self._misplaced_detector
        misplaced_engaged = misplaced_det.is_engaged
        pellet_miss = cfg.misplaced_trigger_delay - misplaced_det.engaged_age
        misplaced_triggered = misplaced_engaged and pellet_miss <= 0
        recurrent_miss = (
            60 * self._config.recurrent_delay_minutes - (p_now - self._last_recurrent_perf_c)
        )
        current_dt = self._started_datetime + timedelta(seconds=p_now - self._p_started)
        recurrent_triggered = (
            self._animal_in_training
            and not self.animal_sleep_window.is_time_present(current_dt.time())
            and recurrent_miss <= 0
        )
        if not (misplaced_triggered or recurrent_triggered):
            min_d = pellet_miss if misplaced_engaged else math.inf
            min_d = min(recurrent_miss, min_d)
            return None if min_d <= 0 else min_d
        rate_remain = cfg.rate_limit_delay + cfg.misplaced_trigger_delay - (p_now - self._disengaged_perf_c)
        if rate_remain > 0:
            logger.verbose("delaying tunnel sweep for %.1fs due to rate limit", rate_remain)
            return rate_remain
        if recurrent_triggered:
            self._last_recurrent_perf_c = p_now
        self.is_engaged = True
        return cfg.tunnel_fan_on_duration

    def _on_pellet_misplaced_property_changed(self, name, value, _):
        if name == self._misplaced_detector.IS_ENGAGED:
            if value:
                self.check_state()
