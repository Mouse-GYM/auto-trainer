"""
Class to manage compound movement configuration YAML file or YAML dictionary.

In either case, the YAML base key for contents is either "magnet" or "pellet".
"pellet" can have 6 subgroups:
* "load" - for load servo configuration
* "cover" - for cover servo configuration
* "x" - for x stepper configuration
* "y" - for y stepper configuration
* "z" - for z stepper configuration

"tunnel" can have 1 subgroup:
* "magnet" - for magnet head servo
"""
import copy
import dataclasses
import logging
import typing

import yaml
from pathlib import Path
from typing import Tuple, Union

from typing_extensions import Self

from autotrainer.core import MotorConfigurations

from .device_interface import ServoConfig, StepperConfig, Motor
from autotrainer.core.logging import get_verbose_logger

logger = get_verbose_logger(__name__)



DEFAULT_TUNNEL_FAN_CONFIG = ServoConfig.from_dict(dict(
    min_pos=0,
    max_pos=100,
    min_pwm=0,
    max_pwm=500,
    max_vel=500.0,
    max_acc=5000.0,
))


class MotorConfigurationFile(MotorConfigurations):
    """
    Implement MotorConfigurations Protocol
    """

    DEFAULT_LOCATION = Path("~/Autotrainer/motor_config.yaml")  # you shall use .expanduser() when you use it

    def __init__(self):
        """
        Define the set of configuration data sets as the defaults of their respective
        motor configuration types.
        """
        self._magnet_config = ServoConfig()
        self._load_config = ServoConfig()
        self._cover_config = ServoConfig()
        self._gate_config = ServoConfig()
        self._x_config = StepperConfig()
        self._y_config = StepperConfig()
        self._z_config = StepperConfig()
        self._tunnel_fan_config = ServoConfig()

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
    def from_yaml_dict(cls, yaml_dict) -> Self:
        """
        Import configurations from a dictionary.

        Args:
            yaml_dict (dict): Dictionary of data

        Returns:
            MotorConfigurationFile: populated with file contents
        """
        inst = cls()
        inst._convert(yaml_dict)
        return inst

    def _load(self, filename: Union[str, Path]):
        """
        Load configurations from a file.

        Args:
            filename (str or Path): Filename to load from
        """
        filename = Path(filename)
        if filename.exists():
            try:
                with filename.open("r") as fh:
                    loaded = self._convert(yaml.safe_load(fh))
            except Exception as e:
                logger.error(f"Alogus motor configuration file {filename}: {e}")
                raise
            else:
                logger.notice("Config %s, loaded: %s", filename, loaded)
                if "tunnel-fan" not in loaded:
                    logger.notice("Auto-adding default tunnel-fan to motor config")
                    self._tunnel_fan_config = copy.deepcopy(DEFAULT_TUNNEL_FAN_CONFIG)
                    self._tunnel_fan_config.motor = Motor.TUNNEL_FAN_SERVO
                if len(loaded) != 8:
                    # x + y + z + pellet load + pellet cover + tunnel-gate + tunnel-magnet + tunnel-fan
                    logger.warning("Expected 8 sections loaded from motor config file %r but got %s: loaded=%s",
                                   filename.as_posix(), len(loaded), loaded)
        else:
            logger.error(f"Alogus motor configuration file {filename}: No such file")

    def _convert(self, yaml_dict):
        """
        Load configurations from a dictionary.

        Args:
            yaml_dict (dict): Dictionary of data
        """
        items_loaded = []
        pellet_dct = yaml_dict.get("pellet", None)
        if pellet_dct is not None:
            load_dct = pellet_dct.get("load")
            if load_dct is not None:
                self._load_config = ServoConfig.from_dict(load_dct)
                self._load_config.motor = Motor.PELLET_LOAD_SERVO
                logger.info("load configuration: %s", self._load_config)
                items_loaded.append("pellet-load")

            barrier_dct = pellet_dct.get("barrier")
            if barrier_dct:
                self._cover_config = ServoConfig.from_dict(barrier_dct)
                self._cover_config.motor = Motor.PELLET_COVER_SERVO
                logger.info("barrier configuration: %s", self._cover_config)
                items_loaded.append("pellet-barrier")

            x_dct = pellet_dct.get("x")
            if x_dct is not None:
                self._x_config = StepperConfig.from_dict(x_dct)
                self._x_config.motor = Motor.PELLET_X_MOTOR
                logger.info("X stepper configuration: %s", self._x_config)
                items_loaded.append("pellet-x")
            #
            y_dct = pellet_dct.get("y")
            if y_dct is not None:
                self._y_config = StepperConfig.from_dict(y_dct)
                self._y_config.motor = Motor.PELLET_Y_MOTOR
                logger.info("Y stepper configuration: %s", self._y_config)
                items_loaded.append("pellet-y")
            #
            z_dct = pellet_dct.get("z")
            if z_dct is not None:
                self._z_config = StepperConfig.from_dict(z_dct)
                self._z_config.motor = Motor.PELLET_Z_MOTOR
                logger.info("Z stepper configuration: %s", self._z_config)
                items_loaded.append("pellet-z")
            #
            fan_dct = pellet_dct.get("tunnel_fan", None)
            if fan_dct is not None:
                self._tunnel_fan_config = ServoConfig.from_dict(fan_dct)
                self._tunnel_fan_config.motor = Motor.TUNNEL_FAN_SERVO
                logger.info("Fan stepper config: %s", self._tunnel_fan_config)
                items_loaded.append("tunnel-fan")

        tunnel_dct = yaml_dict.get("tunnel")
        if tunnel_dct is not None:
            magnet_dct = tunnel_dct.get("magnet", None)
            if magnet_dct is not None:
                self._magnet_config = ServoConfig.from_dict(magnet_dct)
                self._magnet_config.motor = Motor.TUNNEL_MAGNET_SERVO
                logger.info("Magnet stepper configuration: %s", self._magnet_config)
                items_loaded.append("tunnel-magnet")

            gate_dct = tunnel_dct.get("gate", None)
            if gate_dct is not None:
                self._gate_config = ServoConfig.from_dict(gate_dct)
                self._gate_config.motor = Motor.TUNNEL_GATE_SERVO
                logger.info("Gate stepper configuration: %s", self._gate_config)
                items_loaded.append("tunnel-gate")

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
