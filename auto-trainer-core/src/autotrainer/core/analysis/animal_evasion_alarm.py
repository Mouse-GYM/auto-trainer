from typing import Optional

from autotrainer.api import ApiDetectorKind, ApiAlarmKind

from autotrainer.core.analysis.alarm_detector import AlarmDetector
from autotrainer.core.analysis.load_cell_monitor import LoadCellMonitor
from autotrainer.core.analysis.headbar_pressure_monitor import HeadbarPressureMonitor
from autotrainer.core.configuration.autoclamp_evasion_config import AnimalEvasionAlarmConfig


class AnimalEvasionAlarm(AlarmDetector[AnimalEvasionAlarmConfig]):

    config_cls = AnimalEvasionAlarmConfig
    alarm_api_kind = ApiAlarmKind.animalEvasion
