from typing import Optional

import psutil
from autotrainer.api import ApiDetectorKind

from autotrainer.core import PersistenceConfiguration
from autotrainer.core.analysis.detector import BaseDetector
from autotrainer.core.configuration.free_disk_space_config import FreeDiskSpaceConfig
from autotrainer.core.event import post_api_detector_event_content


class FreeDiskSpaceDetector(BaseDetector[FreeDiskSpaceConfig]):

    # detector_api_kind = ApiDetectorKind.lowFreeDiskSpace
    # manually handled in _check_state()
    config_cls = FreeDiskSpaceConfig

    use_daemon = True
    default_timer_delay = 15

    def __init__(self):
        super().__init__()
        self._config.min_limit_mb = 0
        self._persistence_cfg = PersistenceConfiguration(output_location="")

    def _check_state(self) -> Optional[float]:
        cfg = self._config
        loc = self._persistence_cfg.output_location
        if not loc:
            return None
        try:
            usage = psutil.disk_usage(loc)
        except (IOError, PermissionError) as err:
            self._logger.warning("Cannot check disk usage on %r: %s", loc, err)
            engaged = True
        else:
            # usage free is in bytes:
            engaged = usage.free / 2 ** 20 < cfg.min_limit_mb
        prev_engaged = self._is_engaged
        if engaged != prev_engaged:
            post_api_detector_event_content(self._event_manager, ApiDetectorKind.lowFreeDiskSpace,
                                            engaged, self._config.use)
            self.is_engaged = engaged
        return None

    def set_persistence_config(self, config: PersistenceConfiguration):
        self._persistence_cfg = config
        self._logger.verbose("Received persistence config: %s", config)
        self.check_state()
