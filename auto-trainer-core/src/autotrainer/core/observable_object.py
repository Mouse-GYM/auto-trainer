from typing import Protocol

from events import Events


class ObservableObject(Events):
    """Defines a class with a standard property_changed event."""

    def __init__(self, event_names=()):
        super().__init__(event_names + ("property_changed",))

    def _on_property_changed(self, property_name: str, new_value, old_value):
        """Will only generate an event if the new value does not pass a == test with the old value."""
        if old_value == new_value:
            return old_value

        self.property_changed(property_name, new_value, old_value)

        return new_value


class EventSlotProtocol(Protocol):
    def __iadd__(self, f):
        pass

    def __isub__(self, f):
        pass


class ObservableObjectProtocol(Protocol):
    property_changed: EventSlotProtocol
