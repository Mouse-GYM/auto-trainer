"""
Class to manage compound movement configuration YAML file or YAML dictionary.

In either case, the YAML key for contents is "actions".
It can have 7 subgroups:
* "load_pellet" - a sequence of commands for loading a pellet
* "send_pellet" - a sequence of commands for sending the pellet to the cage
* "cover_pellet" - a sequence of commands for covering the pellet
* "release_pellet" - a sequence of commands for uncovering the pellet
* "move_retract" - a sequence of commands for retracting the pellet
* "open_tunnel_gate"
* "close_tunnel_gate"
"""
import enum
import typing
from pathlib import Path
from typing import Dict, Any, Callable

import yaml
from typing_extensions import Self

from autotrainer.core.logging import get_verbose_logger

from .motor_steps import MotorSteps, CompoundMovementDataSet


logger = get_verbose_logger(__name__)


class UniqueKeyLoader(yaml.SafeLoader):

    def construct_mapping(self, node, deep=False):
        mapping = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in mapping:
                raise ValueError(f"Duplicate key detected: '{key}' at line {key_node.start_mark.line + 1}")
            mapping.add(key)
        return super().construct_mapping(node, deep)


class CompoundMovementKind(str, enum.Enum):
    LOAD_PELLET = "load_pellet"
    SEND_PELLET = "send_pellet"
    COVER_PELLET = "cover_pellet"
    RELEASE_PELLET = "release_pellet"
    MOVE_RETRACT = "move_retract"
    OPEN_TUNNEL_GATE = "open_tunnel_gate"
    CLOSE_TUNNEL_GATE = "close_tunnel_gate"


def _make_steps_accessor(kind: CompoundMovementKind):
    def wrapper(self: "CompoundMovements") -> MotorSteps:
        return self._movements[kind]
    wrapper.__name__ = kind.value
    return property(wrapper)


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
    def from_file(cls, filename) -> Self:
        """`
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
            self._convert(yaml.load(fh, UniqueKeyLoader))

    def _convert(self, yaml_dict):
        """
        Load sequences from a dictionary.

        Args:
            yaml_dict (dict): Dictionary of data
        """
        if not isinstance(yaml_dict, dict):
            raise TypeError(f"Expected dict for main compound move content, but got {type(yaml_dict)}")
        try:
            actions = yaml_dict.pop("actions")
        except KeyError:
            raise ValueError("Expected an 'actions' key in main compound move content") from None
        if not isinstance(actions, dict):
            raise TypeError(f"Expected dict for 'actions' in main compound move content, but got {type(actions)}")

        if len(yaml_dict) > 0:
            raise ValueError(f"Unexpected top key(s): {sorted(yaml_dict)}")

        for name, value in actions.items():
            kind = CompoundMovementKind(name)
            if not isinstance(value, (list, tuple)):
                raise TypeError(f"Expected sequence/list for action {name!r}, got {value!r}")
            steps = MotorSteps.from_raw(name, list(value))
            self._movements[kind] = steps
            logger.debug("loaded compound move %r: %s", name, steps)

    '''
    Meet the CompoundMovementDataSet Protocol
    '''

    send_pellet: MotorSteps = _make_steps_accessor(CompoundMovementKind.SEND_PELLET)  # noqa
    load_pellet: MotorSteps = _make_steps_accessor(CompoundMovementKind.LOAD_PELLET)  # noqa
    cover_pellet: MotorSteps = _make_steps_accessor(CompoundMovementKind.COVER_PELLET)  # noqa
    release_pellet: MotorSteps = _make_steps_accessor(CompoundMovementKind.RELEASE_PELLET)  # noqa
    move_retract: MotorSteps = _make_steps_accessor(CompoundMovementKind.MOVE_RETRACT)  # noqa
    open_tunnel_gate: MotorSteps = _make_steps_accessor(CompoundMovementKind.OPEN_TUNNEL_GATE)  # noqa
    close_tunnel_gate: MotorSteps = _make_steps_accessor(CompoundMovementKind.CLOSE_TUNNEL_GATE)  # noqa
