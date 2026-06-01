import dataclasses

from autotrainer.core.configuration.alarm_detector import AlarmDetectorConfig


@dataclasses.dataclass
class SystemMaintenanceConfig(AlarmDetectorConfig):

    use_max_pellet_loaded: bool = True
    auto_resume_on_max_pellets_loaded: bool = True  # actually unused
    max_pellets_loaded_count: int = 500

    use_max_consecutive_failed_load: bool = True
    auto_resume_on_max_consecutive_failed_load: bool = True  # actually unused
    max_consecutive_failed_loaded: int = 10

    use_cage_need_clean: bool = True
    auto_resume_on_cage_cleaned: bool = True  # actually unused
    cage_need_clean_look_ahead_hours: int = 4
