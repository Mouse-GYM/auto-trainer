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

import logging
import yaml
from pathlib import Path
from typing import Tuple

from .device_interface import ServoConfig, StepperConfig, Motor

logger = logging.getLogger(__name__)


class MotorConfigurationFile:

    def __init__(self):
        """
        Define the set of configuration data sets as the defaults of their respective
        motor configuration types.
        """
        self._magnet_config = ServoConfig()
        self._load_config = ServoConfig()
        self._cover_config = ServoConfig()
        self._x_config = StepperConfig()
        self._y_config = StepperConfig()
        self._z_config = StepperConfig()

    @classmethod
    def from_file(cls, filename):
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
    def from_yaml_dict(cls, yaml_dict):
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

    def _load(self, filename):
        """
        Load configurations from a file.

        Args:
            filename (str or Path): Filename to load from
        """
        if isinstance(filename, str):
            filename = Path(filename)

        if filename.exists():
            try:
                with open(filename, "r") as file:
                    self._convert(yaml.safe_load(file))

            except Exception as e:
                logger.error(f"Alogus motor configuration file {filename}: {e}")
        else:
            logger.error(f"Alogus motor configuration file {filename}: No such file")

    def _convert(self, yaml_dict):
        """
        Load configurations from a dictionary.

        Args:
            yaml_dict (dict): Dictionary of data
        """
        if "pellet" in yaml_dict:
            if "load" in yaml_dict["pellet"]:
                self._load_config = ServoConfig.from_dict(yaml_dict["pellet"]["load"])
                self._load_config.motor = Motor.PELLET_LOAD_SERVO
                logger.info(f"load configuration: {self._load_config}")
            if "barrier" in yaml_dict["pellet"]:
                self._cover_config = ServoConfig.from_dict(yaml_dict["pellet"]["barrier"])
                self._cover_config.motor = Motor.PELLET_COVER_SERVO
                logger.info(f"barrier configuration: {self._cover_config}")
            if "x" in yaml_dict["pellet"]:
                self._x_config = StepperConfig.from_dict(yaml_dict["pellet"]["x"])
                self._x_config.motor = Motor.PELLET_X_MOTOR
                logger.info(f"X stepper configuration: {self._x_config}")
            if "y" in yaml_dict["pellet"]:
                self._y_config = StepperConfig.from_dict(yaml_dict["pellet"]["y"])
                self._y_config.motor = Motor.PELLET_Y_MOTOR
                logger.info(f"Y stepper configuration: {self._y_config}")
            if "z" in yaml_dict["pellet"]:
                self._z_config = StepperConfig.from_dict(yaml_dict["pellet"]["z"])
                self._z_config.motor = Motor.PELLET_Z_MOTOR
                logger.info(f"Z stepper configuration: {self._z_config}")
        if "tunnel" in yaml_dict:
            if "magnet" in yaml_dict["tunnel"]:
                self._magnet_config = ServoConfig.from_dict(yaml_dict["tunnel"]["magnet"])
                self._magnet_config.motor = Motor.TUNNEL_MAGNET_SERVO
                logger.info(f"Magnet stepper configuration: {self._magnet_config}")
            if "gate" in yaml_dict["tunnel"]:
                self._gate_config = ServoConfig.from_dict(yaml_dict["tunnel"]["gate"])
                self._gate_config.motor = Motor.TUNNEL_GATE_SERVO
                logger.info(f"Gate stepper configuration: {self._gate_config}")

    '''
    Implement MotorConfigurations Protocol
    '''

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
