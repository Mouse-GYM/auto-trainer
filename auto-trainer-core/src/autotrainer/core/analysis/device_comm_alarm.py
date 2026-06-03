import dataclasses
from typing import Optional

from autotrainer.api import ApiAlarmKind
from autotrainer.core.analysis.alarm_detector import AlarmDetector
from autotrainer.core.configuration.alarm_detector import AlarmDetectorConfig


@dataclasses.dataclass
class DeviceCommAlarmConfig(AlarmDetectorConfig):

    is_emergency_condition: bool = True


class DeviceCommAlarm(AlarmDetector[DeviceCommAlarmConfig]):

    config_cls = DeviceCommAlarmConfig
    alarm_api_kind = ApiAlarmKind.deviceCommunication

    def _check_state(self) -> Optional[float]:
        pass
        # is_engaged is set/handled externally via hardware_model
