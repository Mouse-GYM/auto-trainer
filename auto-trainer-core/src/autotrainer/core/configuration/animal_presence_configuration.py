import dataclasses

from autotrainer.core.configuration.detector import DetectorConfig


@dataclasses.dataclass
class _GlobalAnimalPresenceConfig(DetectorConfig):

    presence_missing_delay_hours: float = 12
    # if mouse not seen in tunnel AND not seen in cage longer than the delay, then trigger


class GlobalAnimalPresenceConfig(_GlobalAnimalPresenceConfig):

    def __init__(self, *,
                 presence_missing_delay: float = None,  # noqa
                 **kwargs):
        del presence_missing_delay  # old param name  # todo: remove some when later
        super().__init__(**kwargs)
