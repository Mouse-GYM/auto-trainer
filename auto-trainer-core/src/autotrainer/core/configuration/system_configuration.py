from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Dict, Optional, Union
from typing_extensions import Self
import yaml

import humps

from .behavior_configuration import BehaviorConfiguration, add_behavior_configuration_representers, \
    add_behavior_configuration_constructors
from .camera_configuration import CameraConfiguration, CameraId, camera_configuration_representer, \
    camera_configuration_constructor
from .hardware_configuration import HardwareConfiguration, hardware_configuration_representer, \
    hardware_configuration_constructor
from .inference_configuration import InferenceConfiguration, inference_configuration_representer, \
    inference_configuration_constructor
from .persistence_configuration import PersistenceConfiguration, persistence_configuration_representer, \
    persistence_configuration_constructor

logger = logging.getLogger(__name__)


@dataclass
class SystemConfiguration:
    """
    The user-visible and editable elements of the system configuration are evolving.  This class is largely intended
    manage transitions and maintain a consistent interface to applications.
    """

    version: int = 1
    cameras: List[CameraConfiguration] = field(default_factory=list)
    hardware: HardwareConfiguration = field(default_factory=HardwareConfiguration)
    inference: InferenceConfiguration = field(default_factory=InferenceConfiguration)
    behavior: BehaviorConfiguration = field(default_factory=BehaviorConfiguration)
    persistence: PersistenceConfiguration = field(default_factory=PersistenceConfiguration)

    _camera_map: Dict[CameraId, CameraConfiguration] = field(default_factory=dict)

    _DEFAULT_NAME: str = "system_configuration"

    @classmethod
    def load_yaml(cls, data) -> Self:
        content = yaml.load(data, Loader=get_system_configuration_loader())

        if isinstance(content, dict):
            content = humps.decamelize(content)
            configuration = cls()
            configuration._deserialize_version_zero(content)
        else:
            configuration = content

        return configuration

    @classmethod
    def load_yaml_file(cls, path: Union[Path, str]) -> Optional[Self]:
        with open(path, "r") as file_contents:
            return SystemConfiguration.load_yaml(file_contents)

    @classmethod
    def load_default(cls, location: str) -> Optional[Self]:
        path = Path(location).joinpath(SystemConfiguration._DEFAULT_NAME + ".yaml")
        if path.is_file():
            return SystemConfiguration.load_yaml_file(path)
        return None

    def save_default(self, location: str):
        path = Path(location).joinpath(SystemConfiguration._DEFAULT_NAME)
        self.save_file(path, as_yaml=True)

    def dump_yaml(self) -> str:
        return yaml.dump(self, Dumper=get_system_configuration_dumper(), sort_keys=False)

    def save_file(self, path: Union[Path, str], as_yaml: bool = False, as_json: bool = False) -> bool:
        try:
            if as_json:
                with open(str(path) + ".json", "w") as file:
                    json.dump(asdict(self), file)
            if as_yaml:
                with open(str(path) + ".yaml", "w") as file:
                    file.write(self.dump_yaml())
        except Exception as err:
            logger.exception("Error saving config to %s: %s", path, err)
            return False

        return True

    def get_camera(self, camera_id: CameraId) -> Optional[CameraConfiguration]:
        if len(self._camera_map) == 0:
            for camera in self.cameras:
                self._camera_map[camera.id] = camera

        return self._camera_map.get(camera_id, None)

    def _deserialize_version_zero(self, content: Dict):
        self.version = 1

        self.cameras.clear()

        self._try_append_version_zero_camera("camera1", content)
        self._try_append_version_zero_camera("camera2", content)
        self._try_append_version_zero_camera("camera3", content)

        # Convenience lookup table.
        for camera in self.cameras:
            self._camera_map[camera.id] = camera

        self.hardware = HardwareConfiguration.from_version_zero(content)

        # Typo from earlier version of the file.
        if "pellet" in content:
            self.inference = InferenceConfiguration.from_version_zero(content["pellet"])

        self.behavior = BehaviorConfiguration.from_version_zero(content)

        self.persistence = PersistenceConfiguration.from_version_zero(content)

    def _try_append_version_zero_camera(self, entry: str, content: Dict) -> bool:
        if entry in content:
            camera = CameraConfiguration.from_version_zero(entry, content[entry])
            if camera is not None:
                self.cameras.append(camera)
                return True

        return False


def system_configuration_representer(dumper: yaml.SafeDumper, c: SystemConfiguration) -> yaml.nodes.MappingNode:
    return dumper.represent_mapping("!SystemConfiguration", {
        "version": c.version,
        "cameras": c.cameras,
        "hardware": c.hardware,
        "inference": c.inference,
        "behavior": c.behavior,
        "persistence": c.persistence
    })


def get_system_configuration_dumper():
    safe_dumper = yaml.SafeDumper

    add_behavior_configuration_representers(safe_dumper)
    safe_dumper.add_representer(CameraConfiguration, camera_configuration_representer)
    safe_dumper.add_representer(HardwareConfiguration, hardware_configuration_representer)
    safe_dumper.add_representer(InferenceConfiguration, inference_configuration_representer)
    safe_dumper.add_representer(PersistenceConfiguration, persistence_configuration_representer)

    safe_dumper.add_representer(SystemConfiguration, system_configuration_representer)

    return safe_dumper


def system_configuration_constructor(loader: yaml.SafeLoader, node: yaml.nodes.MappingNode) -> SystemConfiguration:
    content = loader.construct_mapping(node, deep=True)
    return SystemConfiguration(**humps.decamelize(content))


def get_system_configuration_loader():
    safe_loader = yaml.SafeLoader

    safe_loader.add_constructor("!SystemConfiguration", system_configuration_constructor)
    safe_loader.add_constructor("!CameraConfiguration", camera_configuration_constructor)
    safe_loader.add_constructor("!HardwareConfiguration", hardware_configuration_constructor)
    safe_loader.add_constructor("!InferenceConfiguration", inference_configuration_constructor)
    safe_loader.add_constructor("!PersistenceConfiguration", persistence_configuration_constructor)
    add_behavior_configuration_constructors(safe_loader)

    return safe_loader
