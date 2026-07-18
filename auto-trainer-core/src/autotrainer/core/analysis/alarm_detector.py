import dataclasses
from functools import partial
from typing import Type, TypeVar, Generic, ClassVar, Optional, Callable, Dict, Set, List

from autotrainer.api import ApiAlarmKind, ApiAlarmStatus, ApiEventKind, build_event
from autotrainer.core.analysis.detector import BaseDetector
from autotrainer.core.configuration.alarm_detector import AlarmDetectorConfig


AlarmDetectorConfigT = TypeVar("AlarmDetectorConfigT", bound=AlarmDetectorConfig)


class AlarmDetector(BaseDetector[AlarmDetectorConfigT], Generic[AlarmDetectorConfigT]):
    """Detector base class dedicated to the alarm monitor"""

    config_cls: Type[AlarmDetectorConfigT] = AlarmDetectorConfig
    alarm_api_kind: ClassVar[ApiAlarmKind]

    def __init__(self, *, config: Optional[AlarmDetectorConfigT] = None):
        super().__init__(config=config)
        self.property_changed += self._on_property_changed_cb

    def _on_property_changed_cb(self, name, value, _):
        if name == self.CONFIG:
            self.post_alarm_event()

    def post_alarm_event(self):
        kind = self.alarm_api_kind
        if kind is None:
            return
        cfg = self._config
        self._event_manager.post_api_event(build_event(
            ApiEventKind.alarmChanged,
            ApiAlarmStatus(
                alarm_id=kind,
                is_active=self._is_engaged,
                is_enabled=cfg.use,
                is_stop_condition=cfg.is_emergency_condition,
                is_auto_resume_enabled=cfg.allow_autoresume_on_cleared,
            )))

    def _custom_set_is_engaged(self):
        super()._custom_set_is_engaged()
        self.post_alarm_event()
