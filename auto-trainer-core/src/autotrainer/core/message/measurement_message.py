from typing import Protocol, List


class MeasurementMessage(Protocol):
    @property
    def when(self) -> float:
        pass

    @property
    def index(self) -> int:
        pass

    @property
    def weight(self) -> float:
        pass

    @property
    def pressure(self) -> float:
        pass

    # Deprecated
    @property
    def switch(self) -> float:
        pass

    @property
    def temperature(self) -> float:
        pass

    @property
    def humidity(self) -> float:
        pass

    @property
    def head_contact(self) -> bool:
        pass

    @property
    def spectrum(self) -> List[float]:
        pass
