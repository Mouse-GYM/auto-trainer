from typing import Tuple

from events import Events

from autotrainer.core import MessageHandler


class StateMachine:
    """Generic state machine/object mixin, with events handling"""

    def __init__(self, *, initial_state, event_names: Tuple[str, ...] = ()):
        super().__init__()
        self._state = initial_state
        self._events = Events(event_names + ('state_changed', 'property_changed'))

    @property
    def events(self):
        return self._events

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, new_value):
        if new_value == self._state:
            return
        old_value, self._state = self._state, new_value
        self._events.state_changed(old_value, new_value)
        self._events.property_changed(MessageHandler.STATE_PROPERTY, new_value, old_value)
