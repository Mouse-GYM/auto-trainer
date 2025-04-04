from typing import Protocol

from autotrainer.core import ObservableObjectProtocol, SensorAnalysis


class HeadFixProtocol(ObservableObjectProtocol, Protocol):
    @property
    def head_fix_reader(self) -> SensorAnalysis:
        pass

    def update_position(self, position: float):
        pass

    def tare(self):
        pass
