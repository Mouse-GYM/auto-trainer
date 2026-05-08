import math
from typing import Optional, Callable, Dict, List

from autotrainer.core import get_perf_now, get_verbose_logger
from autotrainer.core.analysis.detector import BaseDetector
from autotrainer.core.configuration.watchdog_config import WatchdogConfig


logger = get_verbose_logger(__name__)


WatchdogEvaluatePerfCounterT = Callable[[], float]


class WatchdogMonitor(BaseDetector):

    use_daemon = True
    default_timer_delay = 1

    def __init__(self):
        super().__init__()
        self._watchdogs: Dict[str, WatchdogEvaluatePerfCounterT] = {}
        self._config = WatchdogConfig()
        self._engaged_watchdogs: List[str] = []

    @property
    def config(self) -> WatchdogConfig:
        return self._config

    @config.setter
    def config(self, value: WatchdogConfig):
        self._config = value

    @property
    def registered_watchdogs(self) -> List[str]:
        return list(self._watchdogs)

    def register_watchdog(self, key: str, getter: WatchdogEvaluatePerfCounterT):
        logger.verbose("registering %s as watchdog with %s", key, getter)
        self._watchdogs[key] = getter

    def unregister_watchdog(self, key: str):
        popped = self._watchdogs.pop(key, None)
        if popped is not None:
            logger.verbose("unregistered %s as watchdog", key)

    @property
    def engaged_watchdogs(self) -> List[str]:
        return sorted(self._engaged_watchdogs)

    def _check_state(self) -> Optional[float]:
        p_now = get_perf_now()
        cfg = self._config
        engaged = set()
        prev_engaged = self._engaged_watchdogs
        for key, watchdog in self._watchdogs.items():
            w_p = watchdog()
            if math.isnan(w_p) or math.isinf(w_p):
                continue
            delay = p_now - w_p
            if delay > cfg.perf_counter_trigger_delay:
                engaged.add(key)
                if key not in prev_engaged:
                    logger.error("detected watchdog %s timed out: %.1f", key, delay)
            elif key in prev_engaged:
                logger.notice("watchdog %s resumed live", key)
        self._engaged_watchdogs = list(engaged)
        self.is_engaged = len(engaged) > 0
