from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from typing_extensions import Self


@dataclass(frozen=True)
class EventInfo:
    """
    EventInfo is a structured definition for "events" in the system.  The primary objective is to provide a history of
    actions and changes that are consequential to animal training in structured format that can be parsed in
    conjunction with outer data files.  This is generally a subset of the information that is needed or useful for
    general logging.
    """
    kind: int
    """
    The kind of event.  This is a unique identifier for the event type. Some coordination is required across modules 
    to prevent id duplication, if desired.  For most event sinks, the `str()` value is also used as part of the 
    output.  Using and `IntEnum` or similar that generates a descriptive string by default is encouraged.
    """
    when: datetime
    """
    The time the event occurred.  This is typically presented as a date/time string in the output.
    """
    index: int
    """
    An time-based index that may be more precise than standard date-time functions.  Typically set via 
    `time.perf_counter_ns()`.  The same method of indexing must be used across all `EventInfo` providers if indexing 
    is expected to be consistent across all event types.
    """
    context: Optional[object] = None
    """
    An optional object containing event specific information.  `EventInfo` collections are typically presented in a
    structured, row-column format.  Complex hierarchical data structures may not be represented well in this format.  
    The object must be serializable to JSON using the default JSON encoder and be pickleable to ensure support in all
    event manager sinks.
    """

    def is_same(self, info: Self) -> bool:
        """
        Provide a deeper than ReferenceEquals comparison of two `EventInfo` objects to determine repeat events.  It is
        less stringent than a raw shallow compare as fields like when and index are expected to be different for repeat
        events.  There may be specialized `EventInfo` instances require a custom comparison of `context` to determine
        sameness in which case this can be overridden in a subclass.

        Args:
            info: another `EventInfo` object to compare against.

        Returns:
            True if the two `EventInfo` objects are the same, False otherwise.
        """
        return info is not None and self.kind == info.kind and self.context == info.context
