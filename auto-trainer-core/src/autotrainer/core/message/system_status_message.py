from enum import IntEnum
from typing import Protocol


class SystemStatusMessageKind(IntEnum):
    FIRMWARE_VERSION = 101,
    PELLET_X = 201
    PELLET_Y = 202,
    PELLET_Z = 203,
    PELLET_LOAD = 204,
    PELLET_COVER = 205,
    HEAD_MAGNET = 206,
    FRONT_DOOR = 301,
    DRAWER_DOOR = 302,
    MEASUREMENTS = 401,

    # Deprecated
    VERSION = -1,
    ACK = -2
    MEASUREMENT = -101,
    STREAM_START = 6,
    UPDATE_X = -2001,
    UPDATE_Y = -2002,
    UPDATE_Z = -2003


class StepperStatusMessage(Protocol):
    @property
    def location(self) -> float:
        pass

    @property
    def status(self) -> int:
        pass

    @property
    def limit_hit(self) -> bool:
        pass


class ServoStatusMessage(Protocol):
    @property
    def location(self) -> float:
        pass

    @property
    def status(self) -> int:
        pass
