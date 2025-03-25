from typing import Protocol

from autotrainer.core import ObservableObjectProtocol, HeadFixReader


class HeadFixProtocol(ObservableObjectProtocol, Protocol):
    @property
    def head_fix_reader(self) -> HeadFixReader:
        pass

    def update_position(self, position: float):
        pass

    def tare(self):
        pass
