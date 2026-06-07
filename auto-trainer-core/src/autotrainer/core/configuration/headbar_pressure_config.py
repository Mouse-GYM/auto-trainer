from dataclasses import dataclass
from typing_extensions import Self

from autotrainer.core.configuration.detector import DetectorConfig


@dataclass
class HeadbarPressureConfiguration(DetectorConfig):
    threshold: float = 20
    duration: float = 0.5

    @classmethod
    def from_version_zero(cls, content: dict) -> Self:
        return cls(
            threshold=content.get("threshold", 30),
            duration=content.get("duration", 0.25)
        )
