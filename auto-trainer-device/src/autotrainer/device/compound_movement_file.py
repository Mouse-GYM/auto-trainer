"""
Class to manage compound movement configuration YAML file or YAML dictionary.

In either case, the YAML key for contents is "actions".
It can have 4 subgroups:
* "load_pellet" - a sequence of commands for loading a pellet
* "send_pellet" - a sequence of commands for sending the pellet to the cage
* "cover_pellet" - a sequence of commands for covering the pellet
* "release_pellet" - a sequence of commands for uncovering the pellet
"""

import logging
from enum import IntEnum
from pathlib import Path
import yaml

from .motor_steps import MotorSteps, CompoundMovementDataSet

logger = logging.getLogger(__name__)


class CompoundMovementFile(CompoundMovementDataSet):
    """
    Class that loads compound movements (MotorSteps) from either a file or
    a YAML-type dictionary.

    Presents the data in the form of a CompoundMovementDataSet Protocol
    """

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

    def __init__(self):
        """
        Set the default movements to an empty sequence
        """
        self._movements = [MotorSteps(), MotorSteps(), MotorSteps(), MotorSteps()]

    @classmethod
    def from_file(cls, filename):
        """
        Import sequences from a file.

        Args:
            filename (str or Path): Filename to load from

        Returns:
            CompoundMovementFile: populated with file contents
        """
        inst = cls()
        inst._load(filename)
        return inst

    @classmethod
    def from_yaml_dict(cls, yaml_dict):
        """
        Import sequences from a dictionary.

        Args:
            yaml_dict (dict): Dictionary of data

        Returns:
            CompoundMovementFile: populated with file contents
        """
        inst = cls()
        inst._convert(yaml_dict)
        return inst

    def _load(self, filename):
        """
        Load sequences from a file.

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
                logger.error(f"ERROR: Alogus Compound Movement file {filename}: {e}")
        else:
            logger.error(f"ERROR: Alogus Compound Movement file {filename}: No such File")

    def _convert(self, yaml_dict):
        """
        Load sequences from a dictionary.

        Args:
            yaml_dict (dict): Dictionary of data
        """
        if "actions" not in yaml_dict:
            return

        sub_dict = yaml_dict["actions"]

        for idx, name in CompoundMovementFile._mapping.items():
            if name in sub_dict:
                self._movements[idx.value] = \
                    MotorSteps.from_dict(name, sub_dict[name])

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
