from autotrainer.core import ObservableObject, LoadCellMonitor, HeadbarPressureMonitor
from autotrainer.core.analysis import LoadCellTareMonitor


class MockLoadCellMonitor(ObservableObject):
    def __init__(self):
        super().__init__()
        self._is_engaged = False

    @property
    def is_engaged(self) -> bool:
        return self._is_engaged

    def mock_load_cell_engaged(self, b: bool):
        self._is_engaged = b
        self.property_changed(LoadCellMonitor.IS_ENGAGED_PROPERTY, b, not b)


class MockHeadbarPressureMonitor(ObservableObject):
    def __init__(self):
        super().__init__()
        self._is_engaged = False

    @property
    def is_engaged(self) -> bool:
        return self._is_engaged

    def mock_load_cell_engaged(self, b: bool):
        self._is_engaged = b
        self.property_changed(HeadbarPressureMonitor.IS_ENGAGED_PROPERTY, b, not b)


class MockSensorAnalysis(ObservableObject):
    def __init__(self):
        super().__init__()

        self.load_cell_monitor = LoadCellMonitor()
        self.headbar_pressure_monitor = HeadbarPressureMonitor()
        self.load_cell_tare_monitor = LoadCellTareMonitor()

    def mock_load_cell_engaged(self, b: bool):
        self.load_cell_monitor.force_engaged(b)

    def mock_headbar_pressure_engaged(self, b: bool):
        self.headbar_pressure_detector.force_engaged(b)
