import dataclasses


@dataclasses.dataclass
class MousePresenceConfig:

    presence_missing_delay: float = 30
