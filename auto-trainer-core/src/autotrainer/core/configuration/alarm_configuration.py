
from dataclasses import dataclass, field


@dataclass
class EmergencyAlarmCondition:
    use: bool = True  # decide if "used by/enabled with" the alarm monitor, or not
    is_emergency_condition: bool = True  # decide if trigger emergency_stop()/_resume(), or not.
    allow_autoresume_on_cleared: bool = True  # decide if, when cleared, emergency_resume() is automatically called or not.


class AudioLoadCellThrashAlarmCondition(EmergencyAlarmCondition):
    use: bool = False
    is_emergency_condition: bool = True
    allow_autoresume_on_cleared: bool = False

    aggregate_delay: float = 5  # up to how long ago to look at previous results
    # ( ( if count of thrashing triggers greater than this (during last aggregate_delay)
    load_cell_thrash_count: int = 3
    # or percent of time it is ON during aggregate_delay
    load_cell_thrash_percent_on: float = 50
    # ) and (
    audio_thrash_count: int = 3  # spectrum thrash count greater than this (during last aggregate_delay)
    audio_thrash_percent_on: float = 50  # or percent of time it is ON during aggregate_delay
    # ) )


# todo: continue: same with other possible alarm conditions
#  then replace in below _EmergencyAlarmConfiguration and everywhere appropriate


@dataclass
class _EmergencyAlarmConfiguration:

    # 1st possible alarm condition
    # audio_load_cell_thrash: AudioLoadCellThrashAlarmCondition = field(default_factory=AudioLoadCellThrashAlarmCondition)
    use_audio_load_cell_thrash: bool = False
    auto_resume_on_audio_load_cell_thrash_resume: bool = False
    audio_load_cell_is_emergency_stop_condition: bool = True
    audio_load_cell_thrash_aggregate_delay: float = 5
    # ( ( if count of thrashing triggers greater than this (during last aggregate_delay)
    load_cell_thrash_count: int = 3
    # or percent of time it is ON during aggregate_delay
    load_cell_thrash_percent_on: float = 50
    # ) and (
    audio_thrash_count: int = 3  # spectrum thrash count greater than this (during last aggregate_delay)
    audio_thrash_percent_on: float = 50  # or percent of time it is ON during aggregate_delay
    # ) )


    #
    # 2nd possible alarm condition
    use_presence_missing_after_exit_tunnel: bool = False
    auto_resume_on_presence_seen_after_exit_tunnel: bool = False
    presence_missing_is_emergency_stop_condition: bool = True
    tunnel_to_cage_presence_missing_delay: float = 5

    # 3rd
    use_external_doors_open: bool = False
    auto_resume_on_external_doors_close: bool = False
    external_doors_open_is_emergency_stop_condition: bool = True

    # 4rd
    use_global_animal_presence: bool = False
    auto_resume_on_global_animal_presence: bool = False
    global_animal_presence_is_emergency_stop_condition: bool = True

    # 5th
    use_device_comm_error: bool = True
    auto_resume_on_device_comm_error: bool = True
    device_comm_error_is_emergency_stop_condition: bool = True

    # 6th
    use_system_maintenance: bool = True
    auto_resume_on_system_maintenance: bool = True
    system_maintenance_is_emergency_stop_condition: bool = False

    # 7th
    use_system_fault: bool = True
    auto_resume_on_system_fault: bool = True
    system_fault_is_emergency_stop_condition: bool = True


@dataclass
class EmergencyAlarmConfiguration(_EmergencyAlarmConfiguration):

    def __init__(self, **kwargs):  # force kwargs
        super().__init__(**kwargs)
