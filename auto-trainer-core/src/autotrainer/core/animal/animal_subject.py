import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from typing_extensions import Self

logger = logging.getLogger(__name__)


@dataclass
class AnimalSubject:
    """A subject in an animal experiment."""
    name: str = ""

    baseline_magnet_intensity: int = 0

    pellet_x: int = 0
    pellet_y: int = 0
    pellet_z: int = 0

    def __repr__(self):
        return f"{self.__class__.__name__}(name={self.name})"

    @classmethod
    def from_file(cls, file_path: str) -> Optional[Self]:
        animal = AnimalSubject()

        with open(file_path, "r") as file:
            try:
                data = json.load(file)

                animal.name = data["name"]

                if "baseline_magnet_intensity" in data:
                    animal.baseline_magnet_intensity = data["baseline_magnet_intensity"]

                if "pellet_x" and "pellet_y" and "pellet_z" in data:
                    animal.pellet_x = data["pellet_x"]
                    animal.pellet_y = data["pellet_y"]
                    animal.pellet_z = data["pellet_z"]
            except Exception as err:
                logger.error("Error loading animal subject from %s: %s", file_path, err)
                return None

        return animal

    def to_file(self, file_path: Path):
        data = {
            "name": self.name,
            "baseline_magnet_intensity": self.baseline_magnet_intensity,
            "pellet_x": self.pellet_x,
            "pellet_y": self.pellet_y,
            "pellet_z": self.pellet_z
        }
        with file_path.open("w") as fh:
            json.dump(data, fh)
