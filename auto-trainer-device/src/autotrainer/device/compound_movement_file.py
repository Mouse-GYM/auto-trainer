"""
Class to manage compound movement configuration YAML file or YAML dictionary.

In either case, the YAML key for contents is "actions".
It can have 5 subgroups:
* "load_pellet" - a sequence of commands for loading a pellet
* "send_pellet" - a sequence of commands for sending the pellet to the cage
* "cover_pellet" - a sequence of commands for covering the pellet
* "release_pellet" - a sequence of commands for uncovering the pellet
* "move_retract" - a sequence of commands for retracting the pellet
"""
import enum
from pathlib import Path
from typing import Dict, Any

import yaml

from autotrainer.core.logging import get_verbose_logger

from .motor_steps import MotorSteps, CompoundMovementDataSet


logger = get_verbose_logger(__name__)


class CompoundMovementKind(str, enum.Enum):
    LOAD_PELLET = "load_pellet"
    SEND_PELLET = "send_pellet"
    COVER_PELLET = "cover_pellet"
    RELEASE_PELLET = "release_pellet"
    MOVE_RETRACT = "move_retract"
    OPEN_TUNNEL_GATE = "open_tunnel_gate"
    CLOSE_TUNNEL_GATE = "close_tunnel_gate"


CompoundMovementByStringValue = {
    kind.value: kind
    for kind in CompoundMovementKind
}


def _make_steps_accessor(kind: CompoundMovementKind) -> MotorSteps:
    def wrapper(self: "CompoundMovements") -> MotorSteps:
        return self._movements[kind] or MotorSteps(kind.value)
    wrapper.__name__ = kind.value
    return property(wrapper)  # noqa


class CompoundMovements(CompoundMovementDataSet):
    """
    Class that loads compound movements (MotorSteps) from either a file or
    a YAML-type dictionary.

    Presents the data in the form of a CompoundMovementDataSet Protocol
    """

    DEFAULT_LOCATION = Path("~/Autotrainer/move_config.yaml")  # you shall use .expanduser() when you use it

    def __init__(self):
        """
        Set the default movements to an empty sequence
        """
        self._movements = {
            kind: MotorSteps(name=kind.value)
            for kind in CompoundMovementKind
        }

    @classmethod
    def from_file(cls, filename):
        """
        Import sequences from a file.

        Args:
            filename (str or Path): Filename to load from

        Returns:
            CompoundMovements: populated with file contents
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
            CompoundMovements: populated with file contents
        """
        inst = cls()
        inst._convert(yaml_dict)
        return inst

    def _load(self, file_path):
        """
        Load sequences from a file.

        Args:
            file_path (str or Path): Filename to load from
        """
        file_path = Path(file_path)
        with file_path.expanduser().open() as fh:
            self._convert(yaml.safe_load(fh))

    def _convert(self, yaml_dict):
        """
        Load sequences from a dictionary.

        Args:
            yaml_dict (dict): Dictionary of data
        """
        if not isinstance(yaml_dict, dict):
            raise TypeError(f"Expected dict for main compound move content, but got {type(yaml_dict)}")
        try:
            actions = yaml_dict["actions"]
        except KeyError:
            raise ValueError("Expected an 'actions' key in main compound move content") from None
        if not isinstance(actions, dict):
            raise TypeError(f"Expected dict for 'actions' in main compound move content, but got {type(actions)}")

        for name, value in actions.items():
            kind = CompoundMovementByStringValue.get(name, None)
            if kind is None:
                logger.warning("Unhandled %r in compound movement definition. value=%s", name, value)
                continue
            if not isinstance(value, (list, tuple)):
                raise TypeError(f"Expected dict for action {name!r}, got {value!r}")
            steps = MotorSteps.from_raw(name, list(value))
            self._movements[kind] = steps
            logger.debug("loaded compound move %r: %s", name, steps)

    '''
    Meet the CompoundMovementDataSet Protocol
    '''

    send_pellet = _make_steps_accessor(CompoundMovementKind.SEND_PELLET)
    load_pellet = _make_steps_accessor(CompoundMovementKind.LOAD_PELLET)
    cover_pellet = _make_steps_accessor(CompoundMovementKind.COVER_PELLET)
    release_pellet = _make_steps_accessor(CompoundMovementKind.RELEASE_PELLET)
    move_retract = _make_steps_accessor(CompoundMovementKind.MOVE_RETRACT)
    open_tunnel_gate = _make_steps_accessor(CompoundMovementKind.OPEN_TUNNEL_GATE)
    close_tunnel_gate = _make_steps_accessor(CompoundMovementKind.CLOSE_TUNNEL_GATE)
