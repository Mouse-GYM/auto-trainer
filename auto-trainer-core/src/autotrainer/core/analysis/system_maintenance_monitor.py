from typing import Optional, Set, List

from .detector import BaseDetector
from ..configuration.system_maintenance_config import SystemMaintenanceConfig


class SystemMaintenanceMonitor(BaseDetector):

    CONFIG = "config"

    MAX_PELLET_LOADED_ENGAGED = "max_pellet_loaded_engaged"

    def __init__(self, *, config: SystemMaintenanceConfig):
        super().__init__()
        self._config = config
        self._max_pellet_loaded_engaged = False
        self._engaged_reasons: Set[str] = set()

    @property
    def config(self) -> SystemMaintenanceConfig:
        return self._config

    @config.setter
    def config(self, value):
        prev, self._config = self._config, value
        self._on_property_changed(self.CONFIG, value, prev)

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

    def _check_state(self) -> Optional[float]:
        cfg = self._config
        reasons = set()
        for reason, use, engaged in (
            (self.MAX_PELLET_LOADED_ENGAGED, cfg.use_max_pellet_loaded, self.max_pellet_loaded_engaged),
        ):
            if use and engaged:
                reasons.add(reason)
        self._engaged_reasons = reasons
        new_engaged = len(reasons) > 0
        self.is_engaged = new_engaged

    def update_pellet_loaded(self, loaded: int):
        cfg = self._config
        engaged = loaded >= cfg.max_pellets_loaded_count
        self.max_pellet_loaded_engaged = engaged
        self._check_state()
