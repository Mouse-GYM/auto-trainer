import dataclasses


@dataclasses.dataclass
class EmergencyAlarmConfiguration:

    aggregate_delay: float = 5  # up to how long ago to look at previous results

    #
    # ( ( if count of thrashing triggers greater than this (during last aggregate_delay)
    load_cell_thrash_count: int = 3
    # or percent of time it is ON during aggregate_delay
    load_cell_thrash_percent_on: float = 50
    # )
    # and
    # (
    spectrum_thrash_count: int = 3  # spectrum thrash count greater than this (during last aggregate_delay)
    spectrum_thrash_percent_on: float = 50  # or percent of time it is O N during aggregate_delay
    # ) )

    # or
    tunnel_to_cage_presence_missing_delay: float = 5

    # then triggers ?
