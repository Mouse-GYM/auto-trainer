import dataclasses
import enum
from typing import Optional, List, Set, Callable, Dict, Union

from autotrainer.api import ApiAlarmKind

from autotrainer.core.analysis.alarm_detector import AlarmDetector
from autotrainer.core.configuration.alarm_detector import AlarmDetectorConfig
from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.multiproc import make_daemon_timer
from autotrainer.core.configuration.alarm_configuration import EmergencyAlarmConfiguration
from autotrainer.core.analysis.detector import GroupBaseDetector, BaseDetector

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


class EmergencyAlarmMonitor(GroupBaseDetector[EmergencyAlarmConfiguration, BaseDetector]):

    config_cls = EmergencyAlarmConfiguration

    def _consider_for_new_engage(self, det):
        if not super()._consider_for_new_engage(det):
            return False
        cfg = det.config
        return not isinstance(cfg, AlarmDetectorConfig) or cfg.is_emergency_condition
