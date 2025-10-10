import dataclasses


@dataclasses.dataclass
class MousePresenceConfig:

    presence_missing_delay: float = 30
    # if mouse not seen in tunnel AND not seen in cage longer than the delay, then trigger
