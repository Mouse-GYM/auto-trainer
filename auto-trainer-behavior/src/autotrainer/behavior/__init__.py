import dataclasses
import enum
import itertools
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


DEFAULT_DIAMOND_TRIANGLE_CONFIG_PATH = Path(
    os.getenv("AUTOTRAINER_DIAMOND_TRIANGLE_CONFIG", "~/Autotrainer/diamond_triangle_offset.yaml")
).expanduser()


_offset_nans = Offset3DTuple(math.nan, math.nan, math.nan)


# keeping top level atm, given not quite sure where to put
@dataclasses.dataclass
class DiamondTriangleOffsetConfig:
    used_position: Offset3DTuple  # motor coordinate used
    measured_offset: Offset3DTuple  # inference coordinate offset between diamond and triangle (diamond - triangle)

    diamond_coord: Offset3DTuple = _offset_nans
    # inference diamond coordinate

    DEFAULT_CONFIG_PATH: ClassVar = DEFAULT_DIAMOND_TRIANGLE_CONFIG_PATH

    # 3 coordinate systems,
    # but each has some axis direction difference (when one increases, the other decreases)
    flips_inference_motor: ClassVar[Offset3DTuple] = Offset3DTuple(1, -1, 1)
    flips_inference_diamond: ClassVar[Offset3DTuple] = Offset3DTuple(-1, -1, 1)

    # defining flips between motor and diamond with flips between motor and inference * flips between inference and diamond:
    flips_motor_diamond: ClassVar[Offset3DTuple] = flips_inference_motor * flips_inference_diamond

    # custom init to ensure kwarg only :
    def __init__(self, *, used_position, measured_offset, diamond_coord=_offset_nans):
        super().__init__()
        self.used_position = used_position
        self.measured_offset = measured_offset
        self.diamond_coord = diamond_coord

    @property
    def fully_valid(self):
        return all(map(math.isfinite,
            itertools.chain(
                self.used_position,
                self.measured_offset,
                self.diamond_coord,
            )))

    @classmethod
    def load_config(cls, cfg_path: Optional[Path]) -> Optional[Self]:
        if cfg_path is None:
            logger.notice("No diamond-triangle offset config path provided")
        else:
            if not cfg_path.expanduser().is_file():
                logger.warning("Diamond triangle config %r not a file", cfg_path.as_posix())
            else:
                logger.verbose("Loading diamond-triangle file %r", cfg_path.as_posix())
                cfg = DiamondTriangleOffsetConfig.from_file(cfg_path)
                if all(math.isfinite(c) for c in cfg.diamond_coord):
                    return cfg
                logger.warning("Diamond coordinate undefined or not finite in config %r",
                               cfg_path.as_posix())
                return cfg
        return None

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
        """Transform an inference coordinate to motor corresponding coordinate,
        relatively to the diamond-triangle known position & relative offset"""
        assert isinstance(inference_xyz, Offset3DTuple), inference_xyz
        return (
            self.flips_inference_motor * (self.measured_offset - inference_xyz)
            + self.used_position
        )

    def inference_to_diamond(self, inference_xyz: Offset3DTuple) -> Offset3DTuple:
        assert isinstance(inference_xyz, Offset3DTuple), inference_xyz
        return self.flips_inference_diamond * inference_xyz

    def motor_to_inference(self, motor_xyz: Offset3DTuple) -> Offset3DTuple:
        assert isinstance(motor_xyz, Offset3DTuple), motor_xyz
        return (
            self.measured_offset
            - self.flips_inference_motor * (motor_xyz - self.used_position)
        )

    def motor_to_diamond(self, motor_xyz: Offset3DTuple) -> Offset3DTuple:
        """Transform the motor coordinate to corresponding triangle coordinate in DCS"""
        assert isinstance(motor_xyz, Offset3DTuple), motor_xyz
        return (
            self.flips_inference_diamond * self.measured_offset
            - self.flips_motor_diamond * (motor_xyz - self.used_position)
        )

    def diamond_to_motor(self, diamond_xyz: Offset3DTuple) -> Offset3DTuple:
        """Transform the triangle coordinate from DCS to corresponding motor coordinates"""
        assert isinstance(diamond_xyz, Offset3DTuple), diamond_xyz
        return (
            self.flips_inference_diamond * self.measured_offset - diamond_xyz
        ) * self.flips_motor_diamond + self.used_position

    def diamond_to_inference(self, diamond_xyz: Offset3DTuple) -> Offset3DTuple:
        assert isinstance(diamond_xyz, Offset3DTuple), diamond_xyz
        return self.flips_inference_diamond * diamond_xyz


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
    MANUAL_WITH_PROTOCOL = "Manual with Protocol"
    AUTOMATIC = "Automatic"


class RecordingEndingReason(str, enum.Enum):
    NA = "NA"
    ALGO_PAUSED = "AlgoPaused"
    EXIT_TUNNEL = "ExitTunnel"
    PELLET_LOADING = "PelletLoading"
    MISSING_ANIMAL_ACTIVITY_TIMEOUT = "MissingAnimalActivityTimeout"


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
