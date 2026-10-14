import math

from typing import Optional, Dict

from autotrainer.api import ApiDetectorKind

from autotrainer.core.analysis.detector import BaseDetector
from autotrainer.core.configuration.boards_hardware_reset_detector_config import BoardsHardwareResetDetectorConfig


class BoardsHardwareResetDetector(BaseDetector[BoardsHardwareResetDetectorConfig]):

    config_cls = BoardsHardwareResetDetectorConfig
    detector_api_kind = ApiDetectorKind.boardUnexpectedReset

    def __init__(self):
        super().__init__()
        self._boards_uptime: Dict[int, float] = {}
        self._reboot_detected: bool = False

    def _start(self):
        super()._start()
        self._boards_uptime.clear()
        self._reboot_detected = False
        self.is_engaged = False

    def update_uptime(self, target: int, uptime_msecs: int, *, is_boot: bool = False):
        uptime_sec = uptime_msecs / 1000
        with self._lock:
            prev = self._boards_uptime.get(target, None)
            self._boards_uptime[target] = uptime_sec
        if is_boot or (prev is not None and uptime_sec < prev):
            prev_up = math.nan if prev is None else prev
            self._logger.notice("Detected board reboot: target=%s is_boot=%s uptime=%.3f prev_up=%.3f",
                                target, is_boot, uptime_sec, prev_up)
            self._reboot_detected = True
            self.check_state()

    def _check_state(self, *, force: bool = False) -> Optional[float]:
        if self._reboot_detected:
            self.is_engaged = True
            self._reboot_detected = False
