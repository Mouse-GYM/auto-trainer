"""
Class to manage compound movement configuration file.
"""

import logging
from enum import IntEnum

import yaml
from pathlib import Path

from .motor_steps import MotorSteps

logger = logging.getLogger(__name__)


class CompoundMovementFile:
    class _Movement(IntEnum):
        LOAD_PELLET = 0
        SEND_PELLET = 1
        COVER_PELLET = 2
        RELEASE_PELLET = 3

    _mapping = {
        _Movement.LOAD_PELLET: "load_pellet",
        _Movement.SEND_PELLET: "send_pellet",
        _Movement.COVER_PELLET: "cover_pellet",
        _Movement.RELEASE_PELLET: "release_pellet"
    }

    def __init__(self, filename):
        self._movements = [MotorSteps(), MotorSteps(), MotorSteps(), MotorSteps()]

        if isinstance(filename, str):
            filename = Path(filename)

        logger.info(f"LOADING: Alogus Compound Movement file: {filename}")

        if filename.exists():
            try:
                with open(filename, "r") as file:
                    conf = yaml.safe_load(file)

                    if "actions" in conf:
                        for idx, name in CompoundMovementFile._mapping:
                            if name in conf["actions"]:
                                self._movements[idx.value] = \
                                    MotorSteps.from_dict(name, conf["actions"][name])

                logging.info("LOADED: Alogus Compound Movement file")

            except Exception as e:
                logger.error(f"ERROR: Alogus Compound Movement file {filename}: {e}")
        else:
            logger.error(f"ERROR: Alogus Motor Configuration file {filename}: No such File")

    '''
    Meet the CompoundMovementDataSet Protocol
    '''
    
    @property
    def load_pellet(self) -> MotorSteps:
        return self._movements[CompoundMovementFile._Movement.LOAD_PELLET.value]

    @property
    def send_pellet(self) -> MotorSteps:
        return self._movements[CompoundMovementFile._Movement.SEND_PELLET.value]

    @property
    def cover_pellet(self) -> MotorSteps:
        return self._movements[CompoundMovementFile._Movement.COVER_PELLET.value]

    @property
    def release_pellet(self) -> MotorSteps:
        return self._movements[CompoundMovementFile._Movement.RELEASE_PELLET.value]
