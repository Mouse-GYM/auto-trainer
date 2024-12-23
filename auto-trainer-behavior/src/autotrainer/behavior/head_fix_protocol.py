from typing import Protocol

from autotrainer.core import ObservableObjectProtocol
from autotrainer.device import HeadFixReader


class HeadFixProtocol(ObservableObjectProtocol, Protocol):
    @property
    def head_fix_reader(self) -> HeadFixReader:
        pass

    def update_position(self, position: float):
        pass

    def tare(self):
        pass
