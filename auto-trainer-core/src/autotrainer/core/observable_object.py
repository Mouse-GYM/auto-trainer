from typing import Protocol

from events import Events


class ObservableObject(Events):
    """
    Defines a class with observable property change events.  This is a common pattern for UI frameworks in
    particular where some form of a view layer and some type of model layer need to communicate changes in a decoupled
    way.  However, it is applicable in many other situations as well.

    The property_changed event is used by one or more listeners to respond to property changes.

    _on_property_changed is a convenience method that will only generate an event if the new value does not pass
    the == test with the old value.  This prevents needless events and more importantly endless recursion when two
    objects are listening to each other to stay in sync (e.g., UI and model where a change may originate in either).
    """

    def __init__(self, event_names=()):
        super().__init__(event_names + ("property_changed",))

    def _on_property_changed(self, property_name: str, new_value, old_value):
        """Will only generate an event if the new value does not pass the == test with the old value."""
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
    """Allow classes that do not inherit from ObservableObject to indicate they support the property_changed event."""
    property_changed: EventSlotProtocol
