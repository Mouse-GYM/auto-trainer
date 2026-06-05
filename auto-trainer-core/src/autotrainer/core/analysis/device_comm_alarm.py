from typing import Optional

from autotrainer.api import ApiAlarmKind
from autotrainer.core.analysis.alarm_detector import AlarmDetector
from autotrainer.core.configuration.device_comm_alarm_config import DeviceCommAlarmConfig


class DeviceCommAlarm(AlarmDetector[DeviceCommAlarmConfig]):

    config_cls = DeviceCommAlarmConfig
    alarm_api_kind = ApiAlarmKind.deviceCommunication

    def _check_state(self) -> Optional[float]:
        pass
        # is_engaged is set/handled externally via hardware_model
