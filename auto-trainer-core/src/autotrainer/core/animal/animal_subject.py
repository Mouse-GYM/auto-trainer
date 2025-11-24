import dataclasses
import json
import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Optional, Dict, Any, List
from typing_extensions import Self

from autotrainer.core import Offset3DTuple

logger = logging.getLogger(__name__)


def _load_old_format(data: Dict[str, Any]):
    kw = {}
    if "name" in data:
        kw['name'] = data["name"]
    if "baseline_magnet_intensity" in data:
        kw['baseline_magnet_intensity'] = data["baseline_magnet_intensity"]
    animal = AnimalSubject(**kw)
    if "pellet_x" in data and "pellet_y" in data and "pellet_z" in data:
        animal.pellet_x = data["pellet_x"]
        animal.pellet_y = data["pellet_y"]
        animal.pellet_z = data["pellet_z"]
    return animal


@dataclass
class AnimalTraining:
    """Animal Training configuration"""

    # NB: protocol == plan ; todo: could/should better be moved to auto-trainer-training repo

    current_protocol: Optional[str] = None
    protocols: List[Dict[str, Any]] = dataclasses.field(default_factory=list)

    def get_plan_progress(self, plan_id: str) -> Optional[Dict[str, Any]]:
        # {"plan_id": self.plan_id,
        #                 "progress_state": self.progress_state,
        #                 "current_phase_id": None if self.current_phase is None else self.current_phase.phase_id,
        #                 "progress": progress
        #                 }
        for prot in self.protocols:
            if prot.get('plan_id') == plan_id:
                return prot
        return None

    def set_plan_progress(self, plan_id: str, progress: Dict[str, Any]):
        for idx, prog in enumerate(self.protocols):
            if prog['plan_id'] == plan_id:
                self.protocols[idx] = progress
                return
        self.protocols.append(progress)


@dataclass
class AnimalSubject:
    """A subject in an animal experiment."""

    name: str = ""
    id: str = None   # handled in post_init

    baseline_magnet_intensity: int = 0

    is_pellet_dcs: bool = False
    pellet_x: float = 0
    pellet_y: float = 0
    pellet_z: float = 0

    training: AnimalTraining = dataclasses.field(default_factory=AnimalTraining)

    def __post_init__(self):
        if self.id is None:
            self.id = str(uuid.uuid4())
        if not self.name:
            self.name = f"Mouse-{self.id}"

    def __repr__(self):
        return f"{self.__class__.__name__}(name={self.name})"

    @classmethod
    def from_file(cls, file_path: str) -> Optional[Self]:
        animal = AnimalSubject()
        with open(file_path, "r") as file:
            try:
                data = json.load(file)
                if "id" not in data:
                    # old format
                    animal = _load_old_format(data)
                else:
                    reach = data.pop('reach')
                    pellet_dev = reach.pop('pelletDevice', None)
                    pellet_dcs = reach.pop('pelletDcs', None)
                    if pellet_dcs is None:
                        src = pellet_dev
                    else:
                        src = pellet_dcs
                    pellet_x, pellet_y, pellet_z = src['x'], src['y'], src['z']
                    training = data.pop('training')
                    animal = AnimalSubject(
                        id=data.pop('id'),
                        name=data.pop('name'),
                        is_pellet_dcs=pellet_dcs is not None,
                        pellet_x=pellet_x,
                        pellet_y=pellet_y,
                        pellet_z=pellet_z,
                        training=AnimalTraining(
                            current_protocol=training.pop('currentProtocol'),
                            protocols=training.pop('protocols'),
                        )
                    )
            except Exception as err:
                logger.error("Error loading animal subject from %s: %s", file_path, err)
                return None

        logger.debug("loaded animal id=%r name=%r pellet=%s is_dcs=%s",
                     animal.id, animal.name, (pellet_x, pellet_y, pellet_z), animal.is_pellet_dcs)

        return animal

    def to_file(self, file_path: Path):
        reach: Dict[str, Any] = {
            "baselineMagnetIntensity": self.baseline_magnet_intensity,
        }
        key = "pelletDcs" if self.is_pellet_dcs else "pelletDevice"
        reach[key] = {'x': self.pellet_x, 'y': self.pellet_y, 'z': self.pellet_z}
        data = {
            "id": self.id,
            "name": self.name,
            "reach": reach,
            "training": {
                'currentProtocol': self.training.current_protocol,
                'protocols': self.training.protocols,
            },
        }
        xyz = Offset3DTuple(self.pellet_x, self.pellet_y, self.pellet_z)
        logger.debug("Saving %s to %s ; xyz=%s", self.name, file_path.as_posix(), xyz.humanize())
        with NamedTemporaryFile("w", delete=False, dir=file_path.parent) as fh:
            json.dump(data, fh, indent=4)
        os.replace(fh.name, file_path)
