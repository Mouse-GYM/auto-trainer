from enum import IntEnum
from typing import Protocol


class SystemStatusMessageKind(IntEnum):
    FIRMWARE_VERSION = 101,
    """Message will contain the firmware version of the device as a string."""
    PELLET_X = 201
    """Message will contain the pellet X motor status as a StepperStatusMessage."""
    PELLET_Y = 202,
    """Message will contain the pellet Y motor status as a StepperStatusMessage."""
    PELLET_Z = 203,
    """Message will contain the pellet Z motor status as a StepperStatusMessage."""
    PELLET_LOAD = 204,
    """Message will contain the pellet load arm servo status as a ServoStatusMessage."""
    PELLET_COVER = 205,
    """Message will contain the pellet cover arm servo status as a ServoStatusMessage."""
    HEAD_MAGNET = 206,
    """Message will contain the head fixation magnet servo status as a ServoStatusMessage."""
    FRONT_DOOR = 301,
    """Message will contain front door status as True (open) or False (closed)."""
    DRAWER_DOOR = 302,
    """Message will contain drawer door status as True (open) or False (closed)."""
    MEASUREMENTS = 401,
    """Message will contain a list of MeasurementMessage objects."""

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
        """Current motor position in mm."""
        pass

    @property
    def status(self) -> int:
        """Current servo status value."""
        pass

    @property
    def limit_hit(self) -> bool:
        """True if the limit switch has been hit, otherwise False."""
        pass


class ServoStatusMessage(Protocol):
    @property
    def location(self) -> float:
        """Current servo position in degrees."""
        pass

    @property
    def status(self) -> int:
        """Current servo status value."""
        pass
