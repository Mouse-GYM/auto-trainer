import dataclasses
from typing import List


@dataclasses.dataclass
class HeadFixMeasurement:
    when: float = 0
    timestamp: int = 0
    weight: float = 0
    switch: float = 0
    pressure: float = 0
    temperature: float = 0
    humidity: float = 0
    spectrum: List[float] = dataclasses.field(default_factory=list)
    head_contact: bool = False
