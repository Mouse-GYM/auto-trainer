import enum
from typing import Optional

from autotrainer.api import ApiAlarmKind
from .alarm_detector import AlarmDetector
from .detector import GroupBaseDetector, BaseDetector, DetectorConfigT

from ..configuration.system_fault_config import SystemFaultConfig


class SystemFaultReason(str, enum.Enum):

    FREE_DISK_SPACE = "free_disk_space"
    WATCHDOG = "watchdog"
    BOARDS_HARDWARE_RESET = "boards_hardware_reset"


class SystemFaultAlarm(GroupBaseDetector[SystemFaultConfig, BaseDetector], AlarmDetector[SystemFaultConfig]):

    config_cls = SystemFaultConfig
    alarm_api_kind = ApiAlarmKind.systemFault
