
import dataclasses
import math
from typing import Optional, Tuple, List

from autotrainer.core import get_perf_now, Offset3DTuple
from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.multiproc import no_op_timer, make_daemon_timer
from autotrainer.core.analysis.detector import BaseDetector
from autotrainer.core.analysis.pellet_position_monitor import PelletMisplacedDetector


logger = get_verbose_logger(__name__)


_offset_nans = Offset3DTuple(math.nan, math.nan, math.nan)


@dataclasses.dataclass
class AutoTunnelSweepConfiguration:
    enabled: bool = False
    misplaced_trigger_delay: float = 5
    tunnel_fan_on_duration: float = 5
    rate_limit_delay: float = 60


class AutoTunnelSweepMonitor(BaseDetector):

    def __init__(
        self, config: AutoTunnelSweepConfiguration,
        *,
        pellet_misplaced_detector: PelletMisplacedDetector,
    ):
        super().__init__()
        self._config = config
        self._misplaced_detector = pellet_misplaced_detector
        self._timer_end_engaged = no_op_timer
        pellet_misplaced_detector.property_changed += self._on_pellet_misplaced_property_changed

    @property
    def config(self) -> AutoTunnelSweepConfiguration:
        return self._config

    @config.setter
    def config(self, value: AutoTunnelSweepConfiguration):
        self._config = value

    def _stop(self):
        self._timer_end_engaged.cancel()
        self.is_engaged = False  # force disengaged on stop

    def _end_engaged(self):
        self.is_engaged = False
        self._misplaced_detector.restart()

    def _check_state(self) -> Optional[float]:
        cfg = self._config
        if not self._running or not cfg.enabled:
            return None
        if not self._misplaced_detector.is_engaged:
            logger.debug("misplaced not engaged")
            self.is_engaged = False
            return None
        p_now = get_perf_now()
        rate_remain = cfg.rate_limit_delay + cfg.misplaced_trigger_delay - (p_now - self._disengaged_perf_c)
        if rate_remain > 0:
            logger.verbose("delaying tunnel sweep for %.1fs due to rate limit", rate_remain)
            return rate_remain
        self.is_engaged = True
        prev_timer_disengage = self._timer_end_engaged
        if prev_timer_disengage is no_op_timer or prev_timer_disengage.finished.is_set():
            timer = self._timer_end_engaged = make_daemon_timer(cfg.tunnel_fan_on_duration, self._end_engaged)
            timer.start()
        return None

    def _on_pellet_misplaced_property_changed(self, name, value, _):
        if not self._running or not self._config.enabled:
            logger.verbose("auto tunnel sweep not enabled")
            return
        if name == self._misplaced_detector.IS_ENGAGED:
            if value:
                delay = self._config.misplaced_trigger_delay
                if delay > 0:
                    with self._lock:
                        timer = self._cur_timer
                        if not timer.finished.is_set():
                            self._logger.debug("timer already in progress")
                        else:
                            self._make_new_timer(delay)
                    return
            # all other cases (pellet misplaced not engaged or trigger delay <= 0):
            self.check_state()
