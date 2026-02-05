
import dataclasses


@dataclasses.dataclass
class _EmergencyAlarmConfiguration:

    # 1st possible alarm condition
    use_audio_load_cell_thrash: bool = False
    auto_resume_on_audio_load_cell_thrash_resume: bool = False

    audio_load_cell_thrash_aggregate_delay: float = 5  # up to how long ago to look at previous results
    #
    # ( ( if count of thrashing triggers greater than this (during last aggregate_delay)
    load_cell_thrash_count: int = 3
    # or percent of time it is ON during aggregate_delay
    load_cell_thrash_percent_on: float = 50
    # )
    # and
    # (
    audio_thrash_count: int = 3  # spectrum thrash count greater than this (during last aggregate_delay)
    audio_thrash_percent_on: float = 50  # or percent of time it is ON during aggregate_delay
    # ) )

    # 2nd possible alarm condition
    use_presence_missing_after_exit_tunnel: bool = False
    auto_resume_on_presence_seen_after_exit_tunnel: bool = False
    tunnel_to_cage_presence_missing_delay: float = 5

    # 3rd
    use_external_doors_open: bool = False
    auto_resume_on_external_doors_close: bool = False

    # 4rd
    use_global_animal_presence: bool = False
    auto_resume_on_global_animal_presence: bool = False


class EmergencyAlarmConfiguration(_EmergencyAlarmConfiguration):

    # NB: using a subclass allows to customize the dataclass init method here:
    # otherwise the possible default factory methods for fields of the extended dataclass are not called.

    def __init__(self, *args,
                 # temporarily:
                 auto_resume_on_cleared: bool = False,  # noqa
                 use_global_mouse_presence_missing: bool = False,  # noqa
                 auto_resume_on_global_mouse_presence: bool = False,  # noqa
                 # was removed from emergency possible condition.
                 **kwargs):
        # no positional arg (safer):
        if len(args) > 0:
            raise TypeError("Only kwargs allowed")
        super().__init__(**kwargs)
