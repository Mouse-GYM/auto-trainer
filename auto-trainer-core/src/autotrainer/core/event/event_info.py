from dataclasses import dataclass

from autotrainer.api import ApiEvent


@dataclass(frozen=True)
class EventInfo(ApiEvent):
    pass
