from typing import Optional, Set, List

import psutil

from autotrainer.api import ApiDetectorKind

from .detector import BaseDetector
from .watchdog_monitor import WatchdogMonitor
from ..configuration.persistence_configuration import PersistenceConfiguration
from ..configuration.system_fault_config import SystemFaultConfig
from ..event import post_api_detector_event_content


class SystemFaultMonitor(BaseDetector[SystemFaultConfig]):

    config_cls = SystemFaultConfig

    use_daemon = True  # for free disk space checks
    default_timer_delay = 30  # secs ; check is very fast so can afford do it regularly

    CONFIG = BaseDetector.CONFIG

    FREE_DISK_SPACE_ENGAGED = "free_disk_space_engaged"
    WATCHDOG_ENGAGED = "watchdog_engaged"

    def __init__(self, *, config: SystemFaultConfig, watchdog_monitor: WatchdogMonitor):
        super().__init__(config=config)
        self._max_pellet_loaded_engaged = False
        self._max_consecutive_failed_load_engaged = False
        self._free_disk_space_engaged = False
        self._engaged_reasons: Set[str] = set()
        self._persistence_cfg = PersistenceConfiguration()
        self._watchdog_mon = watchdog_monitor
        watchdog_monitor.property_changed += self._on_watchdog_property_changed

    def set_persistence_config(self, config: PersistenceConfiguration):
        self._persistence_cfg = config
        self._logger.verbose("Received persistence config: %s", config)

    @property
    def config(self) -> SystemFaultConfig:
        return self._config

    @config.setter
    def config(self, value: SystemFaultConfig):
        prev, self._config = self._config, value
        self._on_property_changed(self.CONFIG, value, prev)
        self._logger.verbose("Received config: %s", value)

    @property
    def engaged_reasons(self) -> List[str]:
        return list(self._engaged_reasons)

    @property
    def free_disk_space_engaged(self):
        return self._free_disk_space_engaged

    @free_disk_space_engaged.setter
    def free_disk_space_engaged(self, value):
        prev, self._free_disk_space_engaged = self._free_disk_space_engaged, value
        self._on_property_changed(self.FREE_DISK_SPACE_ENGAGED, value, prev)
        if value != prev:
            self.check_state_if_not_detector_thread()
            post_api_detector_event_content(self._event_manager, ApiDetectorKind.lowFreeDiskSpace,
                                            value, self._config.use_free_disk_space)

    def _check_free_disk_space(self):
        cfg = self._config
        usage = psutil.disk_usage(self._persistence_cfg.output_location)
        # usage free is in bytes:
        engaged = usage.free / 2 ** 20 < cfg.free_disk_space_min_limit_mb
        self.free_disk_space_engaged = engaged

    def _check_state(self) -> Optional[float]:
        self._check_free_disk_space()
        cfg = self._config
        reasons = set()
        for reason, use, engaged in (
            (self.FREE_DISK_SPACE_ENGAGED, cfg.use_free_disk_space, self._free_disk_space_engaged),
            (self.WATCHDOG_ENGAGED, cfg.use_watchdog, self._watchdog_mon.is_engaged),
        ):
            if use and engaged:
                reasons.add(reason)
        self._engaged_reasons = reasons
        is_engaged = len(reasons) > 0
        if not self._is_engaged and is_engaged:
            self._logger.notice("Engaging with %s", reasons)
        self.is_engaged = is_engaged

    def _on_watchdog_property_changed(self, name, value, _):
        if name == self._watchdog_mon.IS_ENGAGED:
            self.check_state()
