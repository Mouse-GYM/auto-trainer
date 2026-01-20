from enum import IntEnum

from autotrainer.api.api_event_kind import ApiEventKind as _ApiEventKind

extended_enum = {member.name: member.value for member in _ApiEventKind}

extended_enum["externalDoorDetectorChanged"] = 4101

ApiEventKind = IntEnum("ApiEventKind", extended_enum)

# ApiEventKind = _ApiEventKind

__all__ = ["ApiEventKind"]
