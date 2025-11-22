import dataclasses
import json
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any, List
from typing_extensions import Self


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

    id: str = dataclasses.field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""

    baseline_magnet_intensity: int = 0

    pellet_x: int = 0
    pellet_y: int = 0
    pellet_z: int = 0

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
                    pellet_dev = reach.pop('pelletDevice')
                    training = data.pop('training')
                    animal = AnimalSubject(
                        id=data.pop('id'),
                        name=data.pop('name'),
                        pellet_x=pellet_dev.pop('x'),
                        pellet_y=pellet_dev.pop('y'),
                        pellet_z=pellet_dev.pop('z'),
                        training=AnimalTraining(
                            current_protocol=training.pop('currentProtocol'),
                            protocols=training.pop('protocols'),
                        )
                    )
            except Exception as err:
                logger.error("Error loading animal subject from %s: %s", file_path, err)
                return None

        return animal

    def to_file(self, file_path: Path):
        data = {
            "id": self.id,
            "name": self.name,
            "reach": {
                "baselineMagnetIntensity": self.baseline_magnet_intensity,
                "pelletDevice": {'x': self.pellet_x, 'y': self.pellet_y, 'z': self.pellet_z},
                "pelletDcs": None,
            },
            "training": {
                'currentProtocol': self.training.current_protocol,
                'protocols': self.training.protocols,
            },
        }
        logger.info("Saving %s to %s", self.name, file_path.as_posix())
        with file_path.open("w") as fh:
            json.dump(data, fh, indent=4)
