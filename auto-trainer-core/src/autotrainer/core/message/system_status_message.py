from enum import IntEnum
from typing import Protocol


class SystemStatusMessageKind(IntEnum):
    """
    This class defines the messages types that are sent by the device.  If there is a request/command that generates
    a response, the command will be defined in the SystemCommandKind class.

    A message type is sent to the caller with an optional context/data value.  This value is dependent on the message
    type.

    This is implemented and represented in the send_message() method in the DeviceApi class.
    """

    ACKNOWLEDGE = 1
    """
    This message should be send when a command completes along with the context that is provided with the command.  It
    should not be sent with status messages that are generated independently by the hardware.  The is the mechanism by
    which callers determine if and when specific commands are completed.
    """

    FIRMWARE_VERSION = 101
    """Message will contain the firmware version of the device as a string."""
    # TODO: This needs to be more complex than a string now that different modules are part of the same device and
    #  connection.

    PELLET_MOTOR_X = 201
    """Message will contain the pellet X motor status as a StepperStatusMessage."""

    PELLET_MOTOR_Y = 202
    """Message will contain the pellet Y motor status as a StepperStatusMessage."""

    PELLET_MOTOR_Z = 203
    """Message will contain the pellet Z motor status as a StepperStatusMessage."""

    PELLET_LOAD = 204
    """Message will contain the pellet load arm servo status as a ServoStatusMessage."""

    PELLET_COVER = 205
    """Message will contain the pellet cover arm servo status as a ServoStatusMessage."""

    HEAD_MAGNET = 206
    """Message will contain the head fixation magnet servo status as a ServoStatusMessage."""

    TUNNEL_GATE_SERVO = 207
    """Message will contain the tunnel gate servo status as a ServoStatusMessage."""

    PELLET_X = 208
    """Message will contain the pellet X motor position as a float."""

    PELLET_Y = 209
    """Message will contain the pellet Y motor position as a float."""

    PELLET_Z = 210
    """Message will contain the pellet Z motor position as a float."""

    FRONT_DOOR = 301
    """Message will contain front door status as True (open) or False (closed)."""

    DRAWER_DOOR = 302
    """Message will contain drawer door status as True (open) or False (closed)."""

    SPARE_DOOR = 303
    """Message will contain spare door status as True (open) or False (closed)."""

    EXT_BUTTON = 304
    """Message will contain external button status as True (pressed) or False (released)"""

    STIMULUS_INPUTS = 305
    """Message will contain a list of 4 states as True/False"""

    MEASUREMENTS = 401
    """Message will contain a list of MeasurementMessage objects."""

    AUDIO_SPECTRUM = 402
    """Message will contain the audio spectrum data as an array list of float values."""

    MOTOR_CONFIGURATION = 501

    CAMERA_STATUS_CHANGE = 1001

    MEASUREMENT = -101
    """This value is deprecated.  Use MEASUREMENTS if the object you are passing with this identifier conforms to the
    MeasurementMessage protocol."""

    @classmethod
    def is_member(cls, value):
        return value in cls._value2member_map_


class StepperStatusMessage(Protocol):
    @property
    def position(self) -> float:
        """Current motor position in mm."""
        pass

    @property
    def send_position(self) -> float:
        """Current motor delivery position in mm."""
        pass

    @property
    def is_at_limit(self) -> bool:
        """1 if the limit switch has been hit, otherwise 0."""
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
