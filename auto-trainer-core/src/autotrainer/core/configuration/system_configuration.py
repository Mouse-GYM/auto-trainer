from __future__ import annotations

import io
import json
import shutil

from dataclasses import dataclass, field, asdict
from datetime import datetime, time, timezone
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional, Union, ClassVar, TextIO, Type, Any
from typing_extensions import Self

import yaml
import humps
from dacite import Config, from_dict

from autotrainer.core.logging import get_verbose_logger
from . import GenericSafeLoader, SystemConfigurationLoader, SystemConfigurationDumper, SystemConfigurationSafeLoader, \
    time_from_iso
from .alarm_detector import AlarmDetectorConfig
from .autoclamp_evasion_config import AnimalEvasionAlarmConfig, AutoClampEvasionDetectorConfig
from .boards_hardware_reset_detector_config import BoardsHardwareResetDetectorConfig
from .free_disk_space_config import FreeDiskSpaceConfig
from .watchdog_config import WatchdogConfig, WatchdogItemDetectorConfig
from .. import Offset3DTuple, make_camelize_representer, make_decamelize_constructor
from .behavior_configuration import BehaviorConfiguration, add_behavior_configuration_representers, \
    add_behavior_configuration_constructors
from .camera_configuration import CameraConfiguration, CameraId
from .hardware_configuration import HardwareConfiguration
from .inference_configuration import InferenceConfiguration
from .persistence_configuration import PersistenceConfiguration
from ..project.project_info import DATE_FORMAT, TIME_FORMAT

logger = get_verbose_logger(__name__)

#

# renames which occurred at version-52 :
_BEHAVIOR_FIELD_RENAMES = {
    "auto_end_session": "auto_end_trial",
    "batch_session_recording": "batch_trial_recording",
    "auto_close_gate_on_intersession": "auto_close_gate_on_intertrial",
}
_PELLET_FIELD_RENAMES = {
    "is_intersession_analysis_enabled": "is_intertrial_analysis_enabled",
    "is_intersession_pellet_shift_enabled": "is_intertrial_pellet_shift_enabled",
    "max_pellets_per_session": "max_pellets_per_trial",
}

# can merge them together:
_V52_RENAMES = {**_BEHAVIOR_FIELD_RENAMES, **_PELLET_FIELD_RENAMES}

# renames of fields *inside* a behavior sub-config, keyed by that sub-config's (post-rename) key:
_V52_NESTED_RENAMES = {
    "auto_close_gate_on_intertrial": {
        "session_min_duration": "trial_min_duration",
    },
}

# renames which occurred at version-55:
_V55_BEHAVIOR_KEY_RENAMES = {"led_alarm": "animal_sleep_window"}
_V55_NESTED_RENAMES = {
    "animal_sleep_window": {"start_ignore_hour": "start", "stop_ignore_hour": "stop"},
}


def _to_offset3d(value: Any) -> Offset3DTuple:
    if isinstance(value, Offset3DTuple):
        return value
    if isinstance(value, dict):
        return Offset3DTuple(**value)
    return Offset3DTuple(value)


def _to_time(value: Any) -> time:
    if isinstance(value, time):
        return value
    return time_from_iso(value)


def _to_int(value: Any) -> Any:
    # older configs hold whole floats (e.g. 8.0) where an int is declared, which the previous loader never
    # checked.  Anything else is passed through untouched, so genuinely wrong data still raises.
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


# An older config is re-read with GenericSafeLoader, which drops the yaml tags: the values the tags used to
# carry arrive as plain scalars/dicts, and dacite type-checks strictly rather than deferring to __post_init__.
# So it has to be told how to rebuild those types, and to coerce enums from their underlying values.
_MIGRATE_DACITE_CONFIG = Config(
    cast=[Enum],
    type_hooks={
        Offset3DTuple: _to_offset3d,
        time: _to_time,
        int: _to_int,
    },
)


def _camelize_deep(dct):
    for k, v in tuple(dct.items()):
        dct[humps.camelize(k)] = dct.pop(k)
        if isinstance(v, dict):
            _camelize_deep(v)


@dataclass
class SystemConfiguration:
    """
    The user-visible and editable elements of the system configuration are evolving.  This class is largely intended
    manage transitions and maintain a consistent interface to applications.
    """

    DEFAULT_CONFIG_DIR: ClassVar[Path] = Path("~/Autotrainer")  # caller/user must expanduser() on it
    DEFAULT_NAME: ClassVar[str] = "system_configuration"

    DEFAULT_PATH: ClassVar[Path] = DEFAULT_CONFIG_DIR.joinpath(f"{DEFAULT_NAME}.yaml")  # caller/user must expanduser() on it

    version: int = 55

    cameras: List[CameraConfiguration] = field(default_factory=list)
    hardware: HardwareConfiguration = field(default_factory=HardwareConfiguration)
    inference: InferenceConfiguration = field(default_factory=InferenceConfiguration)
    behavior: BehaviorConfiguration = field(default_factory=BehaviorConfiguration)
    persistence: PersistenceConfiguration = field(default_factory=PersistenceConfiguration)
    watchdog: WatchdogConfig = field(default_factory=WatchdogConfig)

    _camera_map = None  # do not include in fields

    def __post_init__(self):
        self._camera_map = {}

    @classmethod
    def load_yaml(cls: Type[Self], data: TextIO, *, file_path: Optional[Path] = None) -> Self:
        raw_content: Dict[str, Any] = yaml.load(data, GenericSafeLoader)
        data.seek(0)
        version = raw_content.get("version", 0)
        if version == SystemConfiguration.version:
            # easy case
            configuration: Self = yaml.load(data, SystemConfigurationLoader)
        elif version < SystemConfiguration.version:
            content = humps.decamelize(raw_content)
            behavior_dct = content.get("behavior", {})
            if version < 52:
                if version == 0:
                    pellet_dct = content.get("pellet", {})
                else:
                    pellet_dct = behavior_dct.get("pellet_delivery", {})
                for old_key, new_key in _V52_RENAMES.items():
                    if old_key in behavior_dct:
                        behavior_dct[new_key] = behavior_dct.pop(old_key)
                        logger.debug("renamed %s -> %s in config", old_key, new_key)
                    if old_key in pellet_dct:
                        pellet_dct[new_key] = pellet_dct.pop(old_key)
                        logger.debug("renamed %s -> %s in config", old_key, new_key)
                for parent_key, nested_renames in _V52_NESTED_RENAMES.items():
                    nested_dct = behavior_dct.get(parent_key)
                    if isinstance(nested_dct, dict):
                        for old_key, new_key in nested_renames.items():
                            if old_key in nested_dct:
                                nested_dct[new_key] = nested_dct.pop(old_key)
                                logger.debug("renamed %s -> %s in config", old_key, new_key)
            if version < 55:
                for old_key, new_key in _V55_BEHAVIOR_KEY_RENAMES.items():
                    if old_key in behavior_dct:
                        behavior_dct[new_key] = behavior_dct.pop(old_key)
                        logger.debug("renamed %s -> %s in config", old_key, new_key)
                for parent_key, nested_renames in _V55_NESTED_RENAMES.items():
                    nested_dct = behavior_dct.get(parent_key)
                    if isinstance(nested_dct, dict):
                        for old_key, new_key in nested_renames.items():
                            if old_key in nested_dct:
                                nested_dct[new_key] = nested_dct.pop(old_key)
                                logger.debug("renamed %s -> %s in config", old_key, new_key)

            if version == 0:
                configuration = cls()
                configuration._deserialize_version_zero(content)
            elif version == 1:
                configuration = cls()
                configuration._deserialize_version_one(content)
            else:
                # dataclass recursive construct from nested dicts:
                configuration: Self = from_dict(data_class=SystemConfiguration, data=content,  # noqa
                                                config=_MIGRATE_DACITE_CONFIG)
        else:
            assert version > SystemConfiguration.version
            logger.warning("Loading configuration version %s while SystemConfiguration.version == %s, "
                           "only considering known config attributes/properties.",
                           version, SystemConfiguration.version)
            configuration: Self = yaml.load(data, SystemConfigurationSafeLoader)

        if version != SystemConfiguration.version and file_path is not None:
            now = datetime.now()
            now_str = now.strftime(f"{DATE_FORMAT}_{TIME_FORMAT}")
            new_p = file_path.parent.joinpath(
                f"{file_path.stem}_v{version}_{now_str}{file_path.suffix}")
            logger.notice("Detected config version change/mismatch, saving old config to %s,"
                          " and replacing with new after.", new_p)
            shutil.copy2(file_path, new_p)
            configuration.version = SystemConfiguration.version
            # and save new one over previous:
            configuration.save_file(file_path.with_suffix(""), as_yaml=True)

        return configuration

    @classmethod
    def load_yaml_file(cls: Type[Self], path: Union[Path, str], *, save_backup: bool = False) -> Self:
        path: Path = Path(path)
        logger.debug("loading configuration from %r", path)
        with path.open() as fh:
            return cls.load_yaml(fh, file_path=path if save_backup else None)

    @classmethod
    def make_default_yaml_config_path(cls, dir_path: Path) -> Path:
        return dir_path.joinpath(f"{SystemConfiguration.DEFAULT_NAME}.yaml")

    @classmethod
    def load_default(cls: Type[Self], location: Union[str, Path], *, save_backup: bool = False) -> Optional[Self]:
        path = cls.make_default_yaml_config_path(Path(location))
        if path.is_file():
            return cls.load_yaml_file(path, save_backup=save_backup)
        logger.debug("cannot load default from %s ; not a file", path)
        return None

    def save_default(self, dir_path: Union[Path, str]):
        path = self.make_default_yaml_config_path(Path(dir_path))
        save_path: Path = path.with_suffix("")  # noqa
        self.save_file(save_path, as_yaml=True)

    def dump_yaml(self) -> str:
        return yaml.dump(self, Dumper=SystemConfigurationDumper,
                         # we sort/iter by dataclasses.fields() order in our representer function
                         sort_keys=False)

    def save_file(self, path: Union[Path, str], as_yaml: bool = False, as_json: bool = False):
        if not (as_json or as_yaml):
            raise ValueError("Missing one of as_json or as_yaml")
        path: Path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if as_json:
            p = path.with_suffix(".json")
            logger.notice("Writing to %r as json", p.as_posix())
            content = json.dumps(asdict(self))
            # dump before writing to file, to prevent empty file on dump issue
            with p.open("w") as file:
                file.write(content)
        if as_yaml:
            p = path.with_suffix(".yaml")
            logger.notice("Writing to %r as yaml", p.as_posix())
            content = self.dump_yaml()
            # dump before writing to file, to prevent empty file on dump issue
            with p.open("w") as file:
                file.write(content)

    def get_camera(self, camera_id: CameraId) -> Optional[CameraConfiguration]:
        if len(self._camera_map) == 0 or camera_id not in self._camera_map:
            for camera in self.cameras:
                self._camera_map[camera.id] = camera

        return self._camera_map.get(camera_id, None)

    def _deserialize_version_zero(self, content: Dict):
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


#

system_configuration_representer = make_camelize_representer("!SystemConfiguration")


_tag_2_cls = dict(
    SystemConfiguration=SystemConfiguration,
    HardwareConfiguration=HardwareConfiguration,
    CameraConfiguration=CameraConfiguration,
    InferenceConfiguration=InferenceConfiguration,
    AlarmDetectorConfig=AlarmDetectorConfig,
    AnimalEvasionAlarmConfig=AnimalEvasionAlarmConfig,
    AutoClampEvasionDetectorConfig=AutoClampEvasionDetectorConfig,
    PersistenceConfiguration=PersistenceConfiguration,
    FreeDiskSpaceConfig=FreeDiskSpaceConfig,
    WatchDogConfig=WatchdogConfig,
    WatchdogItemDetectorConfig=WatchdogItemDetectorConfig,
    BoardsHardwareResetConfig=BoardsHardwareResetDetectorConfig,
)


def add_repr(_tag, _cls):
    SystemConfigurationDumper.add_representer(_cls, make_camelize_representer(f"!{_tag}"))


for tag, cls in _tag_2_cls.items():
    add_repr(tag, cls)


add_behavior_configuration_representers(SystemConfigurationDumper)


for cls in SystemConfigurationLoader, :
    # SystemConfigurationSafeLoader:
    # no need also add on SystemConfigurationSafeLoader given it subclass SystemConfigurationLoader

    for tag, tag_cls in _tag_2_cls.items():
        cls.add_constructor(f"!{tag}", make_decamelize_constructor(tag_cls))

    add_behavior_configuration_constructors(cls)
