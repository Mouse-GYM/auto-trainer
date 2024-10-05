from autotrainer.core import ObservableObject


class MockHeadfixReader(ObservableObject):
    def __init__(self):
        super().__init__()

        self._is_load_cell_engaged = False

    @property
    def is_load_cell_engaged(self):
        return self._is_load_cell_engaged

    @is_load_cell_engaged.setter
    def is_load_cell_engaged(self, b: bool):
        self._is_load_cell_engaged = self._on_property_changed("is_load_cell_engaged", b, self._is_load_cell_engaged)
