from enum import IntEnum


class SystemCommandKind(IntEnum):
    """
    This class defines the commands supported by the device.  If there is a response beyond acknowledgement, it is
    defined in SystemStatusMessageKind.

    Commands are sent to the device with optional data and context information.  The data is specific to the command
    and may not be applicable to all commands.  The context information is provided by the caller and expected back
    as part of the acknowledgement that the command is complete.  Note that complete may mean that the action is fully
    executed (e.g., a move has reached its final position), not simply that the command was sent to the device.

    The above is currently implemented and represented by the send_message() method in the DeviceConnection class.
    """

    # System commands unrelated to actual behavior.
    REQUEST_VERSION = 1,

    # Actions nominally considered part of the tunnel/head fixation unit (magnet module in some nomenclature).
    SET_MAGNET_INTENSITY = 101,
    UPDATE_SCALE_TARE = 102,

    # Actions nominally considered part of the pellet delivery unit.
    READ_MOTOR_CONFIGURATION = 201,
    WRITE_MOTOR_CONFIGURATION = 202,
    SET_LOAD_PROCEDURE = 203,
    SET_SEND_PROCEDURE = 204,
    SET_X = 205,
    SET_Y = 206,
    SET_Z = 207,
    SET_LOAD_SERVO = 208,
    SET_COVER_SERVO = 20,
    SEND_HOME = 210,
    LOAD_PELLET = 211,
    SEND_PELLET = 212,
    RELEASE_PELLET = 213,
    COVER_PELLET = 214,
    SEND_TO_LIMITS = 215,

    # General actions.
    PLAY_TONE = 301,
    SET_RGB_LED = 302,
    SET_DIGITAL_OUTPUT = 303,
    SET_ANALOG_OUTPUT = 304,

    # Not deprecated so long as the original hardware is supported, but a bit esoteric.  It is not necessary for
    # new hardware to support them or for new application/scripts to support them.
    RAW_COMMAND = 1001,  # TODO only used at command line for original hardware.  Remove eventually.
    SETTINGS = 1002,  # TODO Specific to original hardware head fix unit and not used in user apps.  Remove eventually.
    STREAM_START = 1003,  # TODO n/a new hardware, but required for original.
    STREAM_STOP = 1004,  # TODO n/a new hardware, but required for original.

    @classmethod
    def is_member(cls, value):
        return value in cls._value2member_map_
