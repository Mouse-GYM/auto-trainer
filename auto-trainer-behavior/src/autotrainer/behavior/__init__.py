import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, List, Dict, Optional
from typing_extensions import Self

import numpy
import yaml

from autotrainer.core import Offset3DTuple, get_verbose_logger


logger = get_verbose_logger()


# keeping top level atm, given not quite sure where to put
@dataclasses.dataclass
class DiamondTriangleOffsetConfig:
    used_position: Offset3DTuple
    measured_offset: Offset3DTuple

    DEFAULT_CONFIG_PATH: ClassVar = Path("~/Autotrainer/diamond_triangle_offset.yaml")

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



# Protocol first (less strict)
from .inference_protocol import InferenceProtocol, SegmentationConfiguration, DetectionConfiguration


@dataclass
class IntersessionBlock:
    configuration: SegmentationConfiguration
    frame_count: int = 0


@dataclass
class IntersessionDetection:
    configuration: DetectionConfiguration


from .pellet_device_protocol import PelletDeviceProtocol

from .intersession import IntersessionState
from .intersession.intersession_machine import IntersessionMachine
from .pellet import PelletMachine, PelletState
from .behavior_algorithm import BehaviorAlgorithm

from .analysis import intersession_inference, intersession_process
from .system_machine import SystemMachine
from .system_machine_state import SystemState
from .tunnel_device_protocol import TunnelDeviceProtocol
