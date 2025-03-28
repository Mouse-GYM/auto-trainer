"""
Class to manage compound movement configuration file.
"""

import logging
import yaml
from pathlib import Path

from .motor_steps import MotorSteps

logger = logging.getLogger(__name__)


class CompoundMovementFile:

    def __init__(self, filename):
        if isinstance(filename, str):
            filename = Path(filename)

        logger.info(f"LOADING: Alogus Compound Movement file: {filename}")

        load_movement = MotorSteps("load", [])
        home_movement = MotorSteps("home", [])
        send_movement = MotorSteps("send", [])

        if filename.exists():
            try:
                with open(filename, "r") as file:
                    conf = yaml.safe_load(file)

                    if "actions" in conf:
                        if "load" in conf["actions"]:
                            load_movement = MotorSteps.from_dict("load",
                                                                 conf["actions"]["load"])
                        if "home" in conf["actions"]:
                            home_movement = MotorSteps.from_dict("home",
                                                                 conf["actions"]["home"])
                        if "send" in conf["actions"]:
                            send_movement = MotorSteps.from_dict("send",
                                                                 conf["actions"]["send"])

                logging.info("LOADED: Alogus Compound Movement file")

            except Exception as e:
                logger.error(f"ERROR: Alogus Compound Movement file {filename}: {e}")
        else:
            logger.error(f"ERROR: Alogus Motor Configuration file {filename}: No such File")

        self._load_movement = load_movement
        self._home_movement = home_movement
        self._send_movement = send_movement

    '''
    Meet the CompoundMovementDataSet Protocol
    '''

    @property
    def load(self) -> MotorSteps:
        return self._load_movement

    @property
    def home(self) -> MotorSteps:
        return self._home_movement

    @property
    def send(self) -> MotorSteps:
        return self._send_movement
