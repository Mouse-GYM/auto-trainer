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
    def pose_algorithm(self) -> PoseAlgorithm: ...

    def perform_segmentation(self, configuration: SegmentationConfiguration): ...

    def perform_detection(self, configuration: DetectionConfiguration): ...

    def perform_live(self): ...

    # event:
    def detection_result_ready(self, result): ...
