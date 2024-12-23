from dataclasses import dataclass
from typing import Protocol, Callable

from autotrainer.inference import PoseAlgorithm


@dataclass
class SegmentationConfiguration:
    nonce: str
    session_index: int
    complete: Callable[[str, bool], None]


@dataclass
class DetectionConfiguration:
    nonce: str
    complete: Callable[[str, bool], None]


class InferenceProtocol(Protocol):
    @property
    def pose_algorithm(self) -> PoseAlgorithm:
        pass

    def perform_segmentation(self, configuration: SegmentationConfiguration):
        pass

    def perform_detection(self, configuration: DetectionConfiguration):
        pass

    def perform_live(self):
        pass
