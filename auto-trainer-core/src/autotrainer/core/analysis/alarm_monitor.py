import dataclasses
import enum
from functools import partial
from typing import Optional, List, Set, Callable, Dict, Union

from autotrainer.api import ApiEventKind, ApiAlarmKind, ApiAlarmStatus, build_event

from autotrainer.core.analysis.alarm_detector import AlarmDetector
from autotrainer.core.configuration.alarm_detector import AlarmDetectorConfig
from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.multiproc import make_daemon_timer
from autotrainer.core.configuration.alarm_configuration import EmergencyAlarmConfiguration
from autotrainer.core.analysis.detector import BaseDetector, GroupBaseDetector

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


class EmergencyAlarmMonitor(GroupBaseDetector[EmergencyAlarmConfiguration, AlarmDetector]):

    use_daemon = True
    config_cls = EmergencyAlarmConfiguration
    default_timer_delay = 1

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

    def _check_state(self, *, force: bool=False):
        # overloaded _check_state vs GroupBaseDetector, to take into account is_emergency_condition.
        reasons = set()
        prev_reasons = self._engaged_reasons
        for name, ctx in self._sub_detectors.items():
            det = ctx.detector
            cfg = det.config
            if not det.use_daemon and not det.default_timer_delay:
                det.check_state(force=force)
            if (
                det.is_engaged
                and cfg.use
                and (not isinstance(cfg, AlarmDetectorConfig) or cfg.is_emergency_condition)
            ):
                reasons.add(name)
            elif not det.is_engaged:
                if name in prev_reasons and not cfg.allow_autoresume_on_cleared:
                    reasons.add(name)
        #
        is_emergency = len(reasons) > 0
        if is_emergency and not self._is_engaged:
            logger.notice("Engaging emergency: %s", reasons)
        if reasons != self._engaged_reasons:
            self._is_engaged = None  # force trigger again, so that new reasons are seen
            self._engaged_reasons = reasons
        self.is_engaged = len(reasons) > 0
