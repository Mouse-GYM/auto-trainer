"""
Class to import configuration data for motors from a file
"""

import logging
import yaml
from pathlib import Path
from typing import Tuple

from .device_interface import ServoConfig, StepperConfig, Motor
from autotrainer.core.message import ServoConfigMessage, StepperConfigMessage

"""
        config = Path.home().joinpath(".alogus_config.yaml")
        self._load_config_file(config)  # should be last line in __init__()
"""

logger = logging.getLogger(__name__)

# TODO Have a way to provide a dictionary with the data being loaded from conf = yaml.safe_load(file) below and skip
#  the file reading for when this information is subset of a larger configuration file or the changes have been made
#  in memory.
class MotorConfigurationFile:
    def __init__(self, config_file):
        if isinstance(config_file, str):
            config_file = Path(config_file)

        logger.info(f"loading Alogus motor configuration file: {config_file}")

        magnet_config = ServoConfig()
        load_config = ServoConfig()
        cover_config = ServoConfig()
        x_config = StepperConfig()
        y_config = StepperConfig()
        z_config = StepperConfig()

        if config_file.exists():
            try:
                with open(config_file, "r") as file:
                    conf = yaml.safe_load(file)
                    if "pellet" in conf:
                        if "load" in conf["pellet"]:
                            load_config = ServoConfig.from_dict(conf["pellet"]["load"])
                            logger.info(f"load configuration: {load_config}")
                        if "barrier" in conf["pellet"]:
                            cover_config = ServoConfig.from_dict(conf["pellet"]["barrier"])
                            logger.info(f"barrier configuration: {cover_config}")
                        if "x" in conf["pellet"]:
                            x_config = StepperConfig.from_dict(conf["pellet"]["x"])
                            logger.info(f"X stepper configuration: {x_config}")
                        if "y" in conf["pellet"]:
                            y_config = StepperConfig.from_dict(conf["pellet"]["y"])
                            logger.info(f"Y stepper configuration: {y_config}")
                        if "z" in conf["pellet"]:
                            z_config = StepperConfig.from_dict(conf["pellet"]["z"])
                            logger.info(f"Z stepper configuration: {z_config}")
                    if "magnet" in conf:
                        if "head" in conf["magnet"]:
                            magnet_config = ServoConfig.from_dict(conf["magnet"]["head"])
                            logger.info(f"Magnet stepper configuration: {magnet_config}")

                logger.info(f"loaded Alogus motor configuration file: {config_file}")

            except Exception as e:
                logger.error(f"Alogus motor configuration file {config_file}: {e}")
        else:
            logger.error(f"Alogus motor configuration file {config_file}: No such file")

        self._load_config = load_config
        self._cover_config = cover_config
        self._x_config = x_config
        self._y_config = y_config
        self._z_config = z_config
        self._magnet_config = magnet_config

    '''
    Implement MotorConfigurations Protocol
    '''

    @property
    def magnet_config(self) -> Tuple[Motor, ServoConfigMessage]:
        return Motor.MAGNET_SERVO, self._magnet_config

    @property
    def load_config(self) -> Tuple[Motor, ServoConfigMessage]:
        return Motor.PELLET_LOAD_SERVO, self._load_config

    @property
    def cover_config(self) -> Tuple[Motor, ServoConfigMessage]:
        return Motor.PELLET_COVER_SERVO, self._cover_config

    @property
    def x_config(self) -> Tuple[Motor, StepperConfigMessage]:
        return Motor.PELLET_X_MOTOR, self._x_config

    @property
    def y_config(self) -> Tuple[Motor, StepperConfigMessage]:
        return Motor.PELLET_Y_MOTOR, self._y_config

    @property
    def z_config(self) -> Tuple[Motor, StepperConfigMessage]:
        return Motor.PELLET_Z_MOTOR, self._z_config
