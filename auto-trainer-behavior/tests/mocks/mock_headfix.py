from autotrainer.core import ObservableObject, SensorAnalysis


class MockHeadfix(ObservableObject):
    """
    Provides both head fix command and reader interfaces for testing.
    """

    def __init__(self):
        super().__init__()

        self._is_load_cell_engaged = False

        self._is_headbar_pressure_engaged = False

        self._current_position = 0

    def mock_load_cell_engaged(self, b: bool):
        self._is_load_cell_engaged = self._on_property_changed("is_load_cell_engaged", b, self._is_load_cell_engaged)

    def mock_headbar_pressure_engaged(self, b: bool):
        self._is_headbar_pressure_engaged = self._on_property_changed("is_headbar_pressure_engaged", b,
                                                                      self._is_headbar_pressure_engaged)

    @property
    def head_fix_reader(self) -> SensorAnalysis:
        return self

    @property
    def current_position(self):
        return self._current_position

    @property
    def is_headbar_pressure_engaged(self):
        return self._is_headbar_pressure_engaged

    def update_position(self, value: int):
        self._current_position = value

    def tare(self):
        pass
