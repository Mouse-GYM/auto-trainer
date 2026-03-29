import enum
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

# keeping top level atm, given not quite sure where to put

def _unconfigured_complete_action(once, success):
    raise RuntimeError("complete attribute unconfigured")


@dataclass
class SegmentationConfiguration:
    nonce: str
    session_index: int
    session_when: datetime
    complete: Callable[[str, bool], None] = _unconfigured_complete_action


@dataclass
class DetectionConfiguration:
    nonce: str
    session_index: int
    session_when: datetime
    complete: Callable[[str, bool], None] = _unconfigured_complete_action


@dataclass
class IntersessionBlock:
    configuration: SegmentationConfiguration
    frame_count: int = 0


@dataclass
class IntersessionDetection:
    configuration: DetectionConfiguration


class CaptureAnalysisResult(str, enum.Enum):
    CAPTURE_ONLY = "capture_only"
    ANALYSIS_SUCCEEDED = "analysis_succeeded"
    ANALYSIS_FAILED = "analysis_failed"
    ANALYSIS_DELAYED = "analysis_delayed"


class TrainingMode(str, enum.Enum):  # todo: eventually find better place
    MANUAL = "Manual"
    MANUAL_WITH_PROTOCOL = "Manual with Protocol"
    AUTOMATIC = "Automatic"


class RecordingEndingReason(str, enum.Enum):
    NA = "NA"
    ALGO_PAUSED = "AlgoPaused"
    EXIT_TUNNEL = "ExitTunnel"
    PELLET_LOADING = "PelletLoading"
    MISSING_ANIMAL_ACTIVITY_TIMEOUT = "MissingAnimalActivityTimeout"
    MOTOR_DRIFT_HOMING = "MotorDriftHoming"


# Protocol first (less strict)
from .inference_protocol import InferenceProtocol
from .pellet_device_protocol import PelletDeviceProtocol

from .intersession import IntersessionState
from .intersession.intersession_machine import IntersessionMachine
from .behavior_algorithm import BehaviorAlgorithm

from .system_machine import SystemMachine
from .system_machine_state import SystemState
from .tunnel_device_protocol import TunnelDeviceProtocol
