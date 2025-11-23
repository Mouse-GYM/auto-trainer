import dataclasses
import enum
import math
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import ClassVar, List, Dict, Optional, Callable
from typing_extensions import Self

import numpy
import yaml

from autotrainer.core import Offset3DTuple, get_verbose_logger, SystemConfiguration

logger = get_verbose_logger()

# 3 coordinate systems,
# but each has some axis direction difference (when one increases, the other decreases)
flips_inference_motor = Offset3DTuple(1, -1, 1)
flips_inference_diamond = Offset3DTuple(-1, -1, 1)

# defining flips between motor and diamond with flips between motor and inference * flips between inference and diamond:
flips_motor_diamond = flips_inference_motor * flips_inference_diamond


DEFAULT_DIAMOND_TRIANGLE_CONFIG_PATH = Path(
    os.getenv("AUTOTRAINER_DIAMOND_TRIANGLE_CONFIG", "~/Autotrainer/diamond_triangle_offset.yaml")
).expanduser()


# keeping top level atm, given not quite sure where to put
@dataclasses.dataclass
class DiamondTriangleOffsetConfig:
    used_position: Offset3DTuple
    measured_offset: Offset3DTuple

    DEFAULT_CONFIG_PATH: ClassVar = DEFAULT_DIAMOND_TRIANGLE_CONFIG_PATH

    def __init__(self, *, used_position, measured_offset):
        super().__init__()
        self.used_position = used_position
        self.measured_offset = measured_offset

    @classmethod
    def load_config(cls, cfg_path: Optional[Path]) -> Optional[Self]:
        if cfg_path is None:
            logger.notice("No diamond-triangle offset config path provided")
        else:
            if not cfg_path.expanduser().is_file():
                logger.warning("Diamond triangle config %r not a file", cfg_path.as_posix())
            else:
                return DiamondTriangleOffsetConfig.from_file(cfg_path)
        return None

    @property
    def reference_corrected_offset(self):
        return self.measured_offset - self.used_position  # subtract used_position, to have common 0

    @classmethod
    def from_file(cls, path: Path):
        with path.expanduser().open() as fh:
            dct = yaml.safe_load(fh)
        return cls(**dict((k, Offset3DTuple(dct[k])) for k in dct))

    def to_file(self, path: Path):
        with path.expanduser().open("w") as fh:
            d = dataclasses.asdict(self)
            for k, v in d.items():
                d[k] = list(v)  # getting yaml type error with Offset3D
            yaml.safe_dump(d, fh)

    def inference_to_motor(self, inference_xyz: Offset3DTuple) -> Offset3DTuple:
        """Transform an inference "offset" coordinate (which is """
        return (
            flips_inference_motor * (self.measured_offset - inference_xyz)
            + self.used_position
        )

    def motor_to_inference(self, motor_xyz: Offset3DTuple) -> Offset3DTuple:
        return (
            self.measured_offset
            - flips_inference_motor * (motor_xyz - self.used_position)
        )

    def motor_to_diamond(self, motor_xyz: Offset3DTuple) -> Offset3DTuple:
        return (
            flips_inference_diamond * self.measured_offset
            - flips_motor_diamond * (motor_xyz - self.used_position)
        )

    def diamond_to_motor(self, diamond_xyz: Offset3DTuple) -> Offset3DTuple:
        return (
            flips_inference_diamond * self.measured_offset - diamond_xyz
        ) * flips_motor_diamond + self.used_position


@dataclass
class SegmentationConfiguration:
    nonce: str
    session_index: int
    session_when: datetime
    complete: Callable[[str, bool], None]


@dataclass
class DetectionConfiguration:
    nonce: str
    session_index: int
    session_when: datetime
    complete: Callable[[str, bool], None]


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


class TrainingMode(str, enum.Enum):  # todo: eventually find better place
    MANUAL = "Manual"
    MANUAL_AND_PROTOCOL = "Manual with Protocol"
    AUTOMATIC = "Automatic"



# Protocol first (less strict)
from .inference_protocol import InferenceProtocol
from .pellet_device_protocol import PelletDeviceProtocol

from .intersession import IntersessionState
from .intersession.intersession_machine import IntersessionMachine
from .pellet import PelletMachine, PelletState
from .behavior_algorithm import BehaviorAlgorithm

from .system_machine import SystemMachine
from .system_machine_state import SystemState
from .tunnel_device_protocol import TunnelDeviceProtocol
