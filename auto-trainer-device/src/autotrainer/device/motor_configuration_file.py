"""
Class to manage compound motor configuration YAML file or YAML dictionary.

In either case, the YAML base key for contents is either "magnet" or "pellet".
"pellet" can have 6 subgroups:
* "load" - for load servo configuration
* "cover" - for cover servo configuration
* "x" - for x stepper configuration
* "y" - for y stepper configuration
* "z" - for z stepper configuration
* "tunnel_fan" - for tunnel FAN servo config

"tunnel" can have 2 subgroup:
* "magnet" - for magnet head servo config
* "gate" - for tunnel gate servo config
"""
import copy
from functools import partial

import yaml
from pathlib import Path
from typing import Tuple, Union, Dict, Optional, Type, TypeVar

from typing_extensions import Self

from autotrainer.core import MotorConfigurations
from autotrainer.core.logging import get_verbose_logger

from .device_interface import ServoConfig, StepperConfig, Motor

logger = get_verbose_logger(__name__)


DEFAULT_TUNNEL_FAN_CONFIG_DCT = dict(
    min_pos=0,
    max_pos=100,
    min_pwm=0,
    max_pwm=500,
    max_vel=500.0,
    max_acc=5000.0,
)

DEFAULT_TUNNEL_FAN_CONFIG = ServoConfig.from_dict(DEFAULT_TUNNEL_FAN_CONFIG_DCT)


T_MotorConfig = TypeVar("T_MotorConfig", ServoConfig, StepperConfig)


class MotorConfigurationFile(MotorConfigurations):
    """
    Implement MotorConfigurations Protocol
    """

    DEFAULT_LOCATION = Path("~/Autotrainer/motor_config.yaml")  # you shall use .expanduser() when you use it

    _magnet_config: ServoConfig
    _load_config: ServoConfig
    _cover_config: ServoConfig
    _gate_config: ServoConfig
    _x_config: StepperConfig
    _y_config: StepperConfig
    _z_config: StepperConfig
    _tunnel_fan_config: ServoConfig

    def __init__(self):
        """
        Define the set of configuration data sets as the defaults of their respective
        motor configuration types.
        """
        # NB: the following _convert() is actually the main "initializer" of any instance,
        # it ensures we actually set the .motor on each one, or any other needed extra convert:
        self._convert({}, source=None)

    @classmethod
    def from_file(cls, filename: Union[str, Path]) -> Self:
        """
        Import configurations from a file.

        Args:
            filename (str or Path): Filename to load from

        Returns:
            MotorConfigurationFile: populated with file contents
        """
        inst = cls()
        inst._load(filename)
        return inst

    @classmethod
    def from_yaml_dict(cls, yaml_dict, *, source: Optional[str]="NA") -> Self:
        """
        Import configurations from a dictionary.

        Args:
            yaml_dict (dict): Dictionary of data
            source (str): Eventual source of the data

        Returns:
            MotorConfigurationFile: populated with file contents
        """
        inst = cls()
        inst._convert(yaml_dict, source=source)
        return inst

    def _load(self, filename: Union[str, Path]):
        """
        Load configurations from a file.

        Args:
            filename (str or Path): Filename to load from
        """
        filename: Path = Path(filename)
        if filename.exists():
            try:
                with filename.open("r") as fh:
                    loaded = self._convert(yaml.safe_load(fh), source=filename.as_posix())
            except Exception as e:
                logger.error(f"Alogus motor configuration file {filename}: {e}")
                raise
            else:
                logger.notice("Config %s, loaded: %s", filename, loaded)
        else:
            logger.error(f"Alogus motor configuration file {filename}: No such file")

    def _convert(self, yaml_dict, *, source: Optional[str]="NA"):
        """
        Load configurations from a dictionary.

        Args:
            yaml_dict (dict): Dictionary of data
        """
        items_loaded = []

        pellet_dct: Dict = yaml_dict.get("pellet", {})

        def do_load(parent_dct: Dict, section: str, item: str, motor: Motor, config_cls: Type[T_MotorConfig]) -> T_MotorConfig:
            dct: Optional[Dict] = parent_dct.get(section)
            if dct is None:
                cfg = config_cls()
            else:
                cfg = config_cls.from_dict(dct)
                if source is not None:
                    logger.info("%s configuration: %s", item, cfg)
                items_loaded.append(item)
            cfg.motor = motor
            return cfg
        #
        do_load_pellet = partial(do_load, pellet_dct)
        self._load_config = do_load_pellet("load", "pellet-load", Motor.PELLET_LOAD_SERVO, ServoConfig)
        self._cover_config = do_load_pellet("barrier", "pellet-barrier", Motor.PELLET_COVER_SERVO, ServoConfig)
        #
        self._x_config = do_load_pellet("x", "pellet-x", Motor.PELLET_X_MOTOR, StepperConfig)
        self._y_config = do_load_pellet("y", "pellet-y", Motor.PELLET_Y_MOTOR, StepperConfig)
        self._z_config = do_load_pellet("z", "pellet-z", Motor.PELLET_Z_MOTOR, StepperConfig)
        #
        self._tunnel_fan_config = do_load_pellet("tunnel_fan", "tunnel-fan", Motor.TUNNEL_FAN_SERVO, ServoConfig)
        if "tunnel-fan" not in items_loaded:
            if source is not None:
                logger.notice("Auto-adding default tunnel-fan to motor config")
            self._tunnel_fan_config = copy.deepcopy(DEFAULT_TUNNEL_FAN_CONFIG)
            self._tunnel_fan_config.motor = Motor.TUNNEL_FAN_SERVO
        #
        tunnel_dct: Dict = yaml_dict.get("tunnel", {})
        do_load_tunnel = partial(do_load, tunnel_dct)
        #
        self._magnet_config = do_load_tunnel("magnet", "tunnel-magnet", Motor.TUNNEL_MAGNET_SERVO, ServoConfig)
        self._gate_config = do_load_tunnel("gate", "tunnel-gate", Motor.TUNNEL_GATE_SERVO, ServoConfig)
        #
        if len(items_loaded) != 8:
            # x + y + z + pellet load + pellet cover + tunnel-gate + tunnel-magnet + tunnel-fan
            if source is not None:
                logger.warning(
                    "Expected 8 sections loaded from source %r but got %s: loaded=%s",
                    source,
                    len(items_loaded),
                    items_loaded,
                )

        return items_loaded

    @property
    def magnet_config(self) -> Tuple[Motor, ServoConfig]:
        return Motor.TUNNEL_MAGNET_SERVO, self._magnet_config

    @property
    def gate_config(self) -> Tuple[Motor, ServoConfig]:
        return Motor.TUNNEL_GATE_SERVO, self._gate_config

    @property
    def load_config(self) -> Tuple[Motor, ServoConfig]:
        return Motor.PELLET_LOAD_SERVO, self._load_config

    @property
    def cover_config(self) -> Tuple[Motor, ServoConfig]:
        return Motor.PELLET_COVER_SERVO, self._cover_config

    @property
    def x_config(self) -> Tuple[Motor, StepperConfig]:
        return Motor.PELLET_X_MOTOR, self._x_config

    @property
    def y_config(self) -> Tuple[Motor, StepperConfig]:
        return Motor.PELLET_Y_MOTOR, self._y_config

    @property
    def z_config(self) -> Tuple[Motor, StepperConfig]:
        return Motor.PELLET_Z_MOTOR, self._z_config

    @property
    def tunnel_fan_config(self) -> Tuple[Motor, ServoConfig]:
        return Motor.TUNNEL_FAN_SERVO, self._tunnel_fan_config
