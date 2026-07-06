import dataclasses
from functools import partial
from typing import Type, TypeVar, Generic, ClassVar, Optional, Callable, Dict, Set, List

from autotrainer.api import ApiAlarmKind, ApiAlarmStatus, ApiEventKind, build_event
from autotrainer.core.analysis.detector import BaseDetector
from autotrainer.core.configuration.alarm_detector import AlarmDetectorConfig


AlarmDetectorConfigT = TypeVar("AlarmDetectorConfigT", bound=AlarmDetectorConfig)


@dataclasses.dataclass
class AlarmSubDetectorContext:
    detector: BaseDetector
    property_changed_callback: Callable



class AlarmDetector(BaseDetector[AlarmDetectorConfigT], Generic[AlarmDetectorConfigT]):
    """Detector base class dedicated to the alarm monitor"""

    config_cls: Type[AlarmDetectorConfigT] = AlarmDetectorConfig
    alarm_api_kind: ClassVar[Optional[ApiAlarmKind]] = None

    def __init__(self, *, config: Optional[AlarmDetectorConfigT] = None):
        super().__init__(config=config)
        self._engaged_reasons: Set[str] = set()
        self._sub_detectors: Dict[str, AlarmSubDetectorContext] = {}
        self.property_changed += self._on_property_changed_cb

    def _on_property_changed_cb(self, name, value, _):
        if name == self.CONFIG:
            self.post_alarm_event()

    @property
    def engaged_reasons(self) -> List[str]:
        with self._lock:
            return list(self._engaged_reasons)

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

    def get_sub_detector(self, name: str) -> Optional[BaseDetector]:
        with self._lock:
            ctx = self._sub_detectors.get(name, None)
        return None if ctx is None else ctx.detector

    def register_sub_detector(self, name: str, detector: BaseDetector):
        with self._lock:
            self.unregister_sub_detector(name)
            ctx = AlarmSubDetectorContext(
                detector=detector,
                property_changed_callback=partial(self._on_sub_detector_property_changed, detector),
            )
            detector.property_changed += ctx.property_changed_callback
            self._sub_detectors[name] = ctx

    def unregister_sub_detector(self, name: str) -> Optional[BaseDetector]:
        with self._lock:
            ctx = self._sub_detectors.pop(name, None)
            if ctx is None:
                return None
            ctx.detector.property_changed -= ctx.property_changed_callback
        return ctx.detector

    def _on_sub_detector_property_changed(self, detector: BaseDetector, name: str, value, _):
        if name == detector.IS_ENGAGED:
            if value:
                self.is_engaged = True
            else:
                self.check_state()

    def _check_state(self) -> Optional[float]:
        engaged = False
        for sub_name, sub_ctx in self._sub_detectors.items():
            if sub_ctx.detector.is_engaged:
                engaged = True
                break  # no need look others
        self.is_engaged = engaged
