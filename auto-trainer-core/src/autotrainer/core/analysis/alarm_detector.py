from typing import Type, TypeVar, Generic, ClassVar, Optional

from autotrainer.api import ApiDetectorKind
from autotrainer.core.analysis.detector import BaseDetector
from autotrainer.core.configuration.alarm_detector import AlarmDetectorConfig


DetectorConfigT = TypeVar("DetectorConfigT", bound=AlarmDetectorConfig)


class AlarmDetector(BaseDetector, Generic[DetectorConfigT]):
    """Detector base class dedicated to the alarm monitor"""

    CONFIG = "config"

    config_cls: Type[DetectorConfigT]
    api_kind: ClassVar[Optional[ApiDetectorKind]]

    def __init__(self):
        super().__init__()
        self._config = self.config_cls()

    @property
    def config(self) -> DetectorConfigT:
        return self._config

    @config.setter
    def config(self, value: DetectorConfigT):
        prev, self._config = self._config, value
        self.property_changed(self.CONFIG, value, prev)
        self.check_state()
