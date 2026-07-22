import math
import time
from typing import Optional, Callable, Dict, List, Set

from autotrainer.core import get_perf_now, get_verbose_logger
from autotrainer.core.analysis.detector import BaseDetector, GroupBaseDetector
from autotrainer.core.configuration.watchdog_config import WatchdogConfig, WatchdogItemDetectorConfig


logger = get_verbose_logger(__name__)


WatchdogEvaluatePerfCounterT = Callable[[], Optional[float]]


class WatchdogItemDetector(BaseDetector[WatchdogItemDetectorConfig]):

    config_cls = WatchdogItemDetectorConfig
    use_daemon = False
    default_timer_delay = None

    def __init__(
        self,
        name: str,
        perf_c_getter: WatchdogEvaluatePerfCounterT,
        watchdog_mon: "WatchdogMonitor",
    ):
        super().__init__(name=name)
        self._perf_c_getter = perf_c_getter
        self._watchdog_mon = watchdog_mon

    def _check_state(self) -> Optional[float]:
        watch_perf_c = self._perf_c_getter()
        if watch_perf_c is None:
            self._logger.warning("watchdog %s None", self._name)
        if watch_perf_c is None or math.isnan(watch_perf_c):
            engaged = False
        else:
            p_now = get_perf_now()
            age = p_now - watch_perf_c
            timeout = self._config.override_timeout_trigger_delay
            if timeout is None:
                timeout = self._watchdog_mon.config.timeout_trigger_delay
            engaged = age > timeout
            if engaged and not self._is_engaged:
                self._logger.error("watchdog %s timed out: age=%.1fs ; p_now=%.1f timeout_trigger_delay=%.1f",
                             self._name, age, p_now, timeout)
            elif not engaged and self._is_engaged:
                self._logger.notice("watchdog %s recovered from timed out", self._name)
        self.is_engaged = engaged
        return None


class WatchdogMonitor(GroupBaseDetector[WatchdogConfig, WatchdogItemDetector]):

    config_cls = WatchdogConfig

    use_daemon = True
    default_timer_delay = 1  # "refresh" rate

    _sub_detectors: Dict[str, WatchdogItemDetector]

    def register_watchdog(self, name: str, getter: WatchdogEvaluatePerfCounterT):
        watch = WatchdogItemDetector(name, getter, self)
        self.register_sub_detector(name, watch)

    def unregister_watchdog(self, name: str):
        self.unregister_sub_detector(name)

    @property
    def engaged_watchdogs(self) -> List[str]:
        return self.engaged_reasons

    @property
    def watchdog_items(self) -> List[WatchdogItemDetector]:
        with self._lock:
            return [ctx.detector for ctx in self._sub_detectors.values()]
