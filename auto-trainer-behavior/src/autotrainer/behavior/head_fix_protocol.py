from typing import Protocol

from autotrainer.core import ObservableObjectProtocol, SensorAnalysis


class HeadFixProtocol(ObservableObjectProtocol, Protocol):
    def set_position(self, position: float):
        pass

    def tare(self):
        pass
