from typing import Optional, Set, List

import psutil

from .detector import BaseDetector
from ..configuration.persistence_configuration import PersistenceConfiguration
from ..configuration.system_maintenance_config import SystemMaintenanceConfig
from ...api import ApiDetectorKind


class SystemMaintenanceMonitor(BaseDetector):

    CONFIG = "config"

    MAX_PELLET_LOADED_ENGAGED = "max_pellet_loaded_engaged"
    MAX_CONSECUTIVE_FAILED_LOAD_ENGAGED = "max_consecutive_failed_load_engaged"

    def __init__(self, *, config: SystemMaintenanceConfig):
        super().__init__()
        self._config = config
        self._max_pellet_loaded_engaged = False
        self._max_consecutive_failed_load_engaged = False
        self._free_disk_space_engaged = False
        self._engaged_reasons: Set[str] = set()

    @property
    def config(self) -> SystemMaintenanceConfig:
        return self._config

    @config.setter
    def config(self, value):
        prev, self._config = self._config, value
        self._on_property_changed(self.CONFIG, value, prev)
        self._logger.verbose("Received config: %s", value)

    @property
    def engaged_reasons(self) -> List[str]:
        return list(self._engaged_reasons)

    @property
    def max_pellet_loaded_engaged(self):
        return self._max_pellet_loaded_engaged

    @max_pellet_loaded_engaged.setter
    def max_pellet_loaded_engaged(self, value):
        prev, self._max_pellet_loaded_engaged = self._max_pellet_loaded_engaged, value
        self._on_property_changed(self.MAX_PELLET_LOADED_ENGAGED, value, prev)
        if value != prev:
            self.post_detector_event(ApiDetectorKind.pelletRefillCountExceeded, value, self._config.use_max_pellet_loaded)
            self.check_state_if_not_detector_thread()

    @property
    def max_consecutive_failed_load_engaged(self):
        return self._max_consecutive_failed_load_engaged

    @max_consecutive_failed_load_engaged.setter
    def max_consecutive_failed_load_engaged(self, value):
        prev, self._max_consecutive_failed_load_engaged = self._max_consecutive_failed_load_engaged, value
        self._on_property_changed(self.MAX_CONSECUTIVE_FAILED_LOAD_ENGAGED, value, prev)
        if value != prev:
            self.post_detector_event(ApiDetectorKind.consectivePelletLoadFailureExceeded, value,
                                     self._config.use_max_consecutive_failed_load)
            self.check_state_if_not_detector_thread()

    def _check_state(self) -> Optional[float]:
        cfg = self._config
        reasons = set()
        for reason, use, engaged in (
            (self.MAX_PELLET_LOADED_ENGAGED, cfg.use_max_pellet_loaded, self._max_pellet_loaded_engaged),
            (self.MAX_CONSECUTIVE_FAILED_LOAD_ENGAGED, cfg.use_max_consecutive_failed_load, self._max_consecutive_failed_load_engaged),
        ):
            if use and engaged:
                reasons.add(reason)
        self._engaged_reasons = reasons
        prev_engaged = self._is_engaged
        self.is_engaged = len(reasons) > 0
        if not prev_engaged and self._is_engaged:
            self._logger.notice("Engaging with %s", reasons)

    def update_pellet_loaded(self, loaded: int):
        cfg = self._config
        engaged = loaded >= cfg.max_pellets_loaded_count
        self.max_pellet_loaded_engaged = engaged

    def update_failed_pellet_load(self, *, consecutive: int):
        cfg = self._config
        engaged = consecutive >= cfg.max_consecutive_failed_loaded
        self.max_consecutive_failed_load_engaged = engaged
