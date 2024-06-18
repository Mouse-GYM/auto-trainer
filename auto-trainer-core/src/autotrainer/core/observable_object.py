from events import Events


class ObservableObject(Events):
    def __init__(self, event_names=()):
        super().__init__(event_names + ("property_changed",))

    def _on_property_changed(self, property_name: str, new_value, old_value):
        if old_value == new_value:
            return old_value

        self.property_changed(property_name, new_value, old_value)

        return new_value
