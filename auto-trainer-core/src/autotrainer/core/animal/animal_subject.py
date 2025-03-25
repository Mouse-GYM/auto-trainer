import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class AnimalSubject:
    """A subject in an animal experiment."""
    name: str = ""

    baseline_magnet_intensity: int = 0

    pellet_x: int = 0
    pellet_y: int = 0
    pellet_z: int = 0

    @classmethod
    def from_file(cls, file_path: str):
        animal = AnimalSubject()

        with open(file_path, "r") as file:
            try:
                data = json.load(file)

                animal.name = data["name"]
                animal.baseline_magnet_intensity = data["baseline_magnet_intensity"]

                animal.pellet_x = data["pellet_x"]
                animal.pellet_y = data["pellet_y"]
                animal.pellet_z = data["pellet_z"]
            except:
                logger.error(f"Error loading animal subject from {file_path}")
                return None

        return animal

    def to_file(self, file_path: str):
        data = {
            "name": self.name,
            "baseline_magnet_intensity": self.baseline_magnet_intensity,
            "pellet_x": self.pellet_x,
            "pellet_y": self.pellet_y,
            "pellet_z": self.pellet_z
        }

        with open(file_path, "w") as file:
            json.dump(data, file)
