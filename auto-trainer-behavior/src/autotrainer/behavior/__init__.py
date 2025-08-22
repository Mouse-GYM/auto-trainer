import dataclasses
from pathlib import Path
from typing import ClassVar

import yaml

from autotrainer.core import Offset3DTuple


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

    @property
    def reference_corrected_offset(self):
        return self.measured_offset - self.used_position  # subtract used_position, to have common 0

    @classmethod
    def from_file(cls, path: Path):
        with path.expanduser().open() as fh:
            dct = yaml.safe_load(fh)
        return cls(**dict((k, Offset3DTuple(dct[k])) for k in dct))


# Protocol first (less strict)
from .inference_protocol import InferenceProtocol, SegmentationConfiguration, DetectionConfiguration
from .pellet_device_protocol import PelletDeviceProtocol

from .intersession import IntersessionState
from .intersession.intersession_machine import IntersessionMachine
from .pellet import PelletMachine, PelletState
from .behavior_algorithm import BehaviorAlgorithm
from .behavior_event_kind import BehaviorEventKind

from .analysis import intersession_inference, intersession_process
from .system_machine import SystemMachine
from .system_machine_state import SystemState
from .tunnel_device_protocol import TunnelDeviceProtocol
