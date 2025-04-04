from enum import IntEnum


class GymDeviceMessageKind(IntEnum):
    VERSION = -1,
    ACK = -2,
    READ_CONFIG = -3,
    WRITE_CONFIG = -4,
    SET_LOAD_PROCEDURE = -6,
    SET_SEND_PROCEDURE = -7,
    SET_DIGITAL_OUTPUT = -8,
    SET_ANALOG_OUTPUT = -9,
    SET_RGB_LED = -10,
    
    # deprecated
    SET_HOME_PROCEDURE = -5,

    @classmethod
    def is_member(cls, value):
        return value in cls._value2member_map_
