import dataclasses
from functools import partial
from typing import Type, TypeVar, Generic, ClassVar, Optional, Callable, Dict, Set, List

from autotrainer.api import ApiAlarmKind, ApiAlarmStatus, ApiEventKind, build_event
from autotrainer.core.analysis.detector import BaseDetector
from autotrainer.core.configuration.alarm_detector import AlarmDetectorConfig
from autotrainer.core.configuration.detector import DetectorConfig, GroupSubDetectorConfig

AlarmDetectorConfigT = TypeVar("AlarmDetectorConfigT", bound=DetectorConfig)


class AlarmDetector(BaseDetector[AlarmDetectorConfigT], Generic[AlarmDetectorConfigT]):
    """Detector base class dedicated to the alarm monitor"""

    config_cls: Type[AlarmDetectorConfigT] = AlarmDetectorConfig
    alarm_api_kind: ClassVar[Optional[ApiAlarmKind]] = None  # noqa

    def __init__(self, *, name: Optional[str]=None, config: Optional[AlarmDetectorConfigT] = None):
        super().__init__(name=name, config=config)
        self.property_changed += self._on_property_changed_cb

    def _on_property_changed_cb(self, name, value, _):
        if name == self.CONFIG:
            self.post_alarm_event()

    def post_alarm_event(self):
        kind = self.alarm_api_kind
        if kind is None:
            return
        cfg = self._config
        is_enabled = not isinstance(cfg, GroupSubDetectorConfig) or cfg.use
        allow_resume = not isinstance(cfg, GroupSubDetectorConfig) or cfg.allow_autoresume_on_cleared
        is_emerg_cond = not isinstance(cfg, AlarmDetectorConfig) or cfg.is_emergency_condition
        self._event_manager.post_api_event(build_event(
            ApiEventKind.alarmChanged,
            ApiAlarmStatus(
                alarm_id=kind,
                is_active=self._is_engaged,
                is_enabled=is_enabled,
                is_stop_condition=is_emerg_cond,
                is_auto_resume_enabled=allow_resume,
            )))

    def _custom_set_is_engaged(self):
        super()._custom_set_is_engaged()
        self.post_alarm_event()
