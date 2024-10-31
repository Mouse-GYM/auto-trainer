from autotrainer.core import ObservableObject


class MockHeadfix(ObservableObject):
    """
    Provides both head fix command and reader interfaces for testing.
    """
    def __init__(self):
        super().__init__()

        self._is_load_cell_engaged = False

        self._current_position = 0

    def mock_load_cell_engaged(self, b: bool):
        self._is_load_cell_engaged = self._on_property_changed("is_load_cell_engaged", b, self._is_load_cell_engaged)

    @property
    def current_position(self):
        return self._current_position

    def update_position(self, value: int):
        self._current_position = value
