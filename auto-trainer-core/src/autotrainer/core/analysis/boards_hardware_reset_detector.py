import math

from typing import Optional

from autotrainer.core import Offset3DTuple
from autotrainer.core.analysis.detector import BaseDetector
from autotrainer.core.configuration.boards_hardware_reset_detector_config import BoardsHardwareResetDetectorConfig


class BoardsHardwareResetDetector(BaseDetector[BoardsHardwareResetDetectorConfig]):

    config_cls = BoardsHardwareResetDetectorConfig

    def __init__(self):
        super().__init__()
        self._hardware_send_pos = Offset3DTuple.get_nan()
        self._requested_send_pos = Offset3DTuple.get_nan()

    def _start(self):
        super()._start()
        self._hardware_send_pos = Offset3DTuple.get_nan()
        self._requested_send_pos = Offset3DTuple.get_nan()

    def set_send_position(self, pos: Offset3DTuple):
        self._logger.debug("set_send_pos: %s", pos)
        self._requested_send_pos = pos
        self.check_state()

    def set_hardware_send_position(self, pos: Offset3DTuple):
        self._logger.debug("set_hardware_send_pos: %s", pos)
        self._hardware_send_pos = pos
        self.check_state()

    def _check_state(self) -> Optional[float]:
        engaged = (
            # NB: this is only a heuristic,
            # which cannot work if/when SEND-POS is effectively set to (0, 0, 0)
            self._hardware_send_pos == (0, 0, 0)
            and all(math.isfinite(v) for v in self._requested_send_pos)
            and self._requested_send_pos != self._hardware_send_pos
            # so we check for that to not trigger false-positive.
        )
        self._logger.debug("check_state: %s ; %s vs %s", engaged, self._hardware_send_pos, self._requested_send_pos)
        self.is_engaged = engaged
