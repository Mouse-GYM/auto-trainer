from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional, Union, ClassVar
from typing_extensions import Self
import yaml

import humps

from autotrainer.core.logging import get_verbose_logger
from . import GenericSafeLoader, SystemConfigurationLoader, SystemConfigurationDumper
from .. import make_camelize_representer, make_decamelize_constructor
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

logger = get_verbose_logger(__name__)

#


@dataclass
class SystemConfiguration:
    """
    The user-visible and editable elements of the system configuration are evolving.  This class is largely intended
    manage transitions and maintain a consistent interface to applications.
    """

    DEFAULT_NAME: ClassVar[str] = "system_configuration"

    version: int = 2
    cameras: List[CameraConfiguration] = field(default_factory=list)
    hardware: HardwareConfiguration = field(default_factory=HardwareConfiguration)
    inference: InferenceConfiguration = field(default_factory=InferenceConfiguration)
    behavior: BehaviorConfiguration = field(default_factory=BehaviorConfiguration)
    persistence: PersistenceConfiguration = field(default_factory=PersistenceConfiguration)

    _camera_map = None  # do not include in fields

    def __post_init__(self):
        self._camera_map = {}

    @classmethod
    def load_yaml(cls, data, *, file_path: Optional[Path] = None) -> Self:
        raw_content = yaml.load(data, GenericSafeLoader)
        version = raw_content.get("version", 0)  # SystemConfiguration.version)
        if version == SystemConfiguration.version:
            # easy case
            configuration = yaml.load(data, SystemConfigurationLoader)
        elif version < SystemConfiguration.version:
            content = humps.decamelize(raw_content)
            configuration = cls()
            if version == 0:
                configuration._deserialize_version_zero(content)
            elif version == 1:
                configuration._deserialize_version_one(content)
            else:
                raise ValueError(f"Cannot handle deserialize version {version}")
        else:
            assert version > SystemConfiguration.version
            logger.warning("Loading configuration version %s while SystemConfiguration.version=%s, "
                           "this might, or not, succeed.",
                           version, SystemConfiguration.version)
            configuration = yaml.load(data, SystemConfigurationLoader)

        if version != SystemConfiguration.version and file_path is not None:
            now = datetime.now(tz=timezone.utc)
            new_p = file_path.parent.joinpath(
                f"{file_path.stem}.v{version}-{now.isoformat(timespec='minutes')}{file_path.suffix}")
            logger.notice("Detected config version change, saving old config to %s", new_p)
            shutil.copy2(file_path, new_p)
            # and save new one over previous:
            configuration.save_file(file_path.with_suffix(""), as_yaml=True)

        return configuration

    @classmethod
    def load_yaml_file(cls, path: Union[Path, str], *, save_backup: bool = True) -> Optional[Self]:
        path = Path(path)
        logger.debug("loading configuration from %r", path)
        with path.open() as fh:
            data = fh.read()  # load_yaml makes several pass, so pre-read and pass the entire content data
            return SystemConfiguration.load_yaml(data, file_path=path if save_backup else None)

    @classmethod
    def make_default_yaml_config_path(cls, location: Path) -> Path:
        return location.joinpath(f"{SystemConfiguration.DEFAULT_NAME}.yaml")

    @classmethod
    def load_default(cls, location: Union[str, Path]) -> Optional[Self]:
        path = cls.make_default_yaml_config_path(Path(location))
        if path.is_file():
            return SystemConfiguration.load_yaml_file(path)
        logger.debug("cannot load default from %s ; not a file", path)
        return None

    def save_default(self, location: Union[Path, str]):
        path = self.make_default_yaml_config_path(Path(location))
        self.save_file(path, as_yaml=True)

    def dump_yaml(self) -> str:
        return yaml.dump(self, Dumper=SystemConfigurationDumper, sort_keys=False)

    def save_file(self, path: Union[Path, str], as_yaml: bool = False, as_json: bool = False) -> bool:
        path = str(path)
        try:
            if as_json:
                p = f"{path}.json"
                logger.notice("Writing to %r as json", p)
                with open(p, "w") as file:
                    json.dump(asdict(self), file)
            if as_yaml:
                p = f"{path}.yaml"
                logger.notice("Writing to %r as yaml", p)
                with open(p, "w") as file:
                    file.write(self.dump_yaml())
        except Exception as err:
            logger.exception("Error saving config to %s: %s", path, err)
            return False

        return True

    def get_camera(self, camera_id: CameraId) -> Optional[CameraConfiguration]:
        if len(self._camera_map) == 0 or camera_id not in self._camera_map:
            for camera in self.cameras:
                self._camera_map[camera.id] = camera

        return self._camera_map.get(camera_id, None)

    def _deserialize_version_zero(self, content: Dict):
        # self.version = self.__class__.version

        self.cameras.clear()

        self._try_append_version_zero_camera("camera1", content)
        self._try_append_version_zero_camera("camera2", content)
        self._try_append_version_zero_camera("camera3", content)

        self.hardware = HardwareConfiguration.from_version_zero(content)

        # Typo from earlier version of the file.
        self.inference = InferenceConfiguration.from_version_zero(content.get("pellet", {}))

        self.behavior = BehaviorConfiguration.from_version_zero(content)
        self.persistence = PersistenceConfiguration.from_version_zero(content)

    def _try_append_version_zero_camera(self, entry: str, content: Dict) -> bool:
        if entry in content:
            camera = CameraConfiguration.from_version_zero(entry, content[entry])
            if camera is not None:
                self.cameras.append(camera)
                return True

        return False

    def _deserialize_version_one(self, content: Dict):
        self.cameras = [
            CameraConfiguration(**kw)
            for kw in content.get("cameras", [])
        ]
        self.hardware = HardwareConfiguration(**content.get("hardware", {}))
        self.inference = InferenceConfiguration(**content.get("inference", {}))
        self.behavior = BehaviorConfiguration.from_version_one(content.get("behavior", {}))
        self.persistence = PersistenceConfiguration(**content.get("persistence", {}))


system_configuration_representer = make_camelize_representer("!SystemConfiguration")


add_behavior_configuration_representers(SystemConfigurationDumper)

SystemConfigurationDumper.add_representer(CameraConfiguration, camera_configuration_representer)
SystemConfigurationDumper.add_representer(HardwareConfiguration, hardware_configuration_representer)
SystemConfigurationDumper.add_representer(InferenceConfiguration, inference_configuration_representer)
SystemConfigurationDumper.add_representer(PersistenceConfiguration, persistence_configuration_representer)

SystemConfigurationDumper.add_representer(SystemConfiguration, system_configuration_representer)

#

system_configuration_constructor = make_decamelize_constructor(SystemConfiguration)

SystemConfigurationLoader.add_constructor("!SystemConfiguration", system_configuration_constructor)
SystemConfigurationLoader.add_constructor("!CameraConfiguration", camera_configuration_constructor)
SystemConfigurationLoader.add_constructor("!HardwareConfiguration", hardware_configuration_constructor)
SystemConfigurationLoader.add_constructor("!InferenceConfiguration", inference_configuration_constructor)
SystemConfigurationLoader.add_constructor("!PersistenceConfiguration", persistence_configuration_constructor)
add_behavior_configuration_constructors(SystemConfigurationLoader)
