

from autotrainer.api import ApiAlarmKind

from autotrainer.core.analysis.alarm_detector import AlarmDetector
from autotrainer.core.analysis.detector import GroupBaseDetector
from autotrainer.core.configuration.autoclamp_evasion_config import AnimalEvasionAlarmConfig


class AnimalEvasionAlarm(GroupBaseDetector, AlarmDetector[AnimalEvasionAlarmConfig]):

    config_cls = AnimalEvasionAlarmConfig
    alarm_api_kind = ApiAlarmKind.animalEvasion
