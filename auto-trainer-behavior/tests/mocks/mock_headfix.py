from autotrainer.core import ObservableObject, SensorAnalysis, LoadCellMonitor


class MockHeadfix(ObservableObject):
    """
    Provides both head fix command and reader interfaces for testing.
    """

    def __init__(self):
        super().__init__()

        self._current_position = 0

    @property
    def current_position(self):
        return self._current_position

    def update_head_magnet_intensity(self, value: float):
        self._current_position = value

    def tare(self):
        pass
