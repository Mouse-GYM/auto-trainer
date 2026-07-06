import dataclasses
import enum
from functools import partial
from typing import Optional, List, Set, Callable, Dict, Union

from autotrainer.api import ApiEventKind, ApiAlarmKind, ApiAlarmStatus, build_event

from autotrainer.core.analysis.alarm_detector import AlarmDetector
from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.multiproc import make_daemon_timer
from autotrainer.core.configuration.alarm_configuration import EmergencyAlarmConfiguration
from autotrainer.core.analysis.detector import BaseDetector


logger = get_verbose_logger(__name__)

timer_update_state = make_daemon_timer


class EmergencyReason(str, enum.Enum):

    ANIMAL_EVASION = "ANIMAL_EVASION"
    MOUSE_THRASHING = "MOUSE_THRASHING"
    IN_CAGE_AFTER_EXIT_TUNNEL = "IN_CAGE_AFTER_EXIT_TUNNEL"
    DOORS_OPEN = "DOORS_OPEN"
    GLOBAL_ANIMAL_PRESENCE = "GLOBAL_ANIMAL_PRESENCE"
    DEVICE_COMM_ERROR = "DEVICE_COMM_ERROR"
    SYSTEM_MAINTENANCE = "SYSTEM_MAINTENANCE"
    SYSTEM_FAULT = "SYSTEM_FAULT"


AlarmDetectorNameT = Union[str, EmergencyReason]


_map_emergency_reason_2_api_alarm_kind = {
    EmergencyReason.ANIMAL_EVASION: ApiAlarmKind.animalEvasion,
    EmergencyReason.MOUSE_THRASHING: ApiAlarmKind.thrashing,
    EmergencyReason.IN_CAGE_AFTER_EXIT_TUNNEL: ApiAlarmKind.animalMissing,
    EmergencyReason.GLOBAL_ANIMAL_PRESENCE: ApiAlarmKind.animalImmobile,
    EmergencyReason.DEVICE_COMM_ERROR: ApiAlarmKind.deviceCommunication,
    EmergencyReason.SYSTEM_FAULT: ApiAlarmKind.systemFault,
    EmergencyReason.SYSTEM_MAINTENANCE: ApiAlarmKind.systemMaintenance,
    EmergencyReason.DOORS_OPEN: ApiAlarmKind.externalDoors,
}


def emergency_reason_2_api_alarm_kind(reason: EmergencyReason) -> ApiAlarmKind:
    return _map_emergency_reason_2_api_alarm_kind[reason]


@dataclasses.dataclass
class AlarmDetectorContext:
    detector: AlarmDetector
    property_changed_callback: Callable


class EmergencyAlarmMonitor(BaseDetector[EmergencyAlarmConfiguration]):

    use_daemon = True
    config_cls = EmergencyAlarmConfiguration
    default_timer_delay = 1

    ALARM_DETECTOR_PROPERTY_CHANGED = "alarm_detector_property_changed"

    def __init__(self):
        super().__init__()
        self._alarms: Dict[str, AlarmDetectorContext] = {}
        self._engaged_reasons: Set[EmergencyReason] = set()

    @property
    def alarms(self) -> Dict[str, AlarmDetectorContext]:
        with self._lock:
            return dict(self._alarms)

    def get_alarm_detector(self, name: AlarmDetectorNameT) -> Optional[AlarmDetector]:
        with self._lock:
            ctx = self._alarms.get(name, None)
            return None if ctx is None else ctx.detector

    def register_detector(self, name: AlarmDetectorNameT, detector: AlarmDetector):
        with self._lock:
            self.unregister_detector(name)
            ctx = AlarmDetectorContext(
                detector=detector,
                property_changed_callback=partial(self._on_detector_property_changed, detector),
            )
            self._alarms[name] = ctx
            detector.property_changed += ctx.property_changed_callback

    def unregister_detector(self, name: AlarmDetectorNameT) -> Optional[AlarmDetector]:
        with self._lock:
            ctx = self._alarms.pop(name, None)
            if ctx is not None:
                ctx.detector.property_changed -= ctx.property_changed_callback
                return ctx.detector
        return None

    def _start(self):
        super()._start()
        self._engaged_reasons.clear()

    def post_alarm_event(self, alarm_id: ApiAlarmKind, active: bool, enabled: bool, auto_resume: bool,
                         is_stop_cond: bool):
        self._event_manager.post_api_event(build_event(
            ApiEventKind.alarmChanged,
            ApiAlarmStatus(
                alarm_id=alarm_id,
                is_active=active,
                is_enabled=enabled,
                is_auto_resume_enabled=auto_resume,
                is_stop_condition=is_stop_cond,
            )))

    @property
    def engaged_reasons(self) -> List[EmergencyReason]:
        return sorted(self._engaged_reasons)

    def _check_state(self):
        reasons = set()
        for name, condition_ctx in self._alarms.items():
            det = condition_ctx.detector
            if not det.use_daemon and det.default_timer_delay == 0:
                det.check_state()
            cond_cfg = det.config
            if det.is_engaged and cond_cfg.use and cond_cfg.is_emergency_condition:
                reasons.add(name)
        #
        is_emergency = len(reasons) > 0
        #
        if is_emergency and not self._is_engaged:
            logger.notice("Engaging emergency: %s", reasons)
        #
        if not is_emergency:
            prev_engaged = self._engaged_reasons
            check_reasons = prev_engaged.copy()
            # look if previous engaged reasons (which are now cleared), allowed auto-resume, or not.
            # if any does not allow : don't remove the is_engaged.
            for prev_r in prev_engaged:
                if prev_r in self._alarms:
                    ctx = self._alarms[prev_r]
                    det = ctx.detector
                    if det.config.allow_autoresume_on_cleared:
                        check_reasons.remove(prev_r)
            #
            self._engaged_reasons = check_reasons  # always reset with what remains in check_reasons.
            if len(check_reasons) == 0 and len(prev_engaged) > 0:
                self._is_engaged = None  # force refresh
                self.is_engaged = False
            elif check_reasons != prev_engaged:
                self._is_engaged = None  # force refresh
                self.is_engaged = True
        else:
            check_reasons = self._engaged_reasons.copy()
            # if some possible condition were previously present and are not auto-resume enabled,
            # then re-add them to current reasons of engaged.
            for prev_r in list(check_reasons):
                if prev_r in self._alarms:
                    ctx = self._alarms[prev_r]
                    det = ctx.detector
                    if not det.config.allow_autoresume_on_cleared:
                        reasons.add(prev_r)
            if reasons != self._engaged_reasons:
                self._is_engaged = None  # force trigger again, so that new reasons are seen
                self._engaged_reasons = reasons
            self.is_engaged = True

    def _on_detector_property_changed(self, detector: AlarmDetector, name: str, value, old_value):
        logger.verbose("%s: %s=%r", detector.name, name, value)
        if name in (detector.IS_ENGAGED, detector.CONFIG):
            self.check_state()
        self.property_changed(self.ALARM_DETECTOR_PROPERTY_CHANGED, (detector, name, value), old_value)
