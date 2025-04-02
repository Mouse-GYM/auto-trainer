from enum import IntEnum


class GymDeviceMessageKind(IntEnum):
    VERSION = -1,
    ACK = -2,
    READ_CONFIG = -3,
    WRITE_CONFIG = -4,
    SET_LOAD_PROCEDURE = -6,
    SET_SEND_PROCEDURE = -7,

    # deprecated
    SET_HOME_PROCEDURE = -5,

    @classmethod
    def is_member(cls, value):
        return value in cls._value2member_map_
