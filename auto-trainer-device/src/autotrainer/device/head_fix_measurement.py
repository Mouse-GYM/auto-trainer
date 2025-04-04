import typing


class HeadFixMeasurement:
    when: float = 0
    timestamp: int = 0
    weight: float = 0
    switch: float = 0
    pressure: float = 0
    temperature: float = 0
    humidity: float = 0
    spectrum: typing.List[float] = []
    head_contact: bool = False

    def __init__(self, when: float = 0, timestamp: int = 0, weight: float = 0, switch: float = 0,
                 pressure: float = 0,
                 temperature: float = 0, humidity: float = 0,
                 spectrum: typing.Optional[typing.List[float]] = None):
        self.when = when
        self.timestamp = timestamp
        self.weight = weight
        self.switch = switch
        self.pressure = pressure
        self.temperature = temperature
        self.humidity = humidity
        self.spectrum = spectrum if spectrum is not None else []
