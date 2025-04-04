from enum import IntEnum


class PelletDeliveryMessageKind(IntEnum):
    RAW_COMMAND = 100,
    SEND_HOME = 101,
    LOAD_PELLET = 102,
    SEND_PELLET = 103,
    RELEASE_PELLET = 104,
    COVER_PELLET = 105,
    SET_X = 106,
    SET_Y = 107,
    SET_Z = 108,
    SEND_TO_LIMITS = 109,
    PLAY_TONE = 110,
    SET_LOAD_SERVO = 111,
    SET_COVER_SERVO = 112,

    # Deprecated
    UPDATE_X = -2001
    UPDATE_Y = -2002,
    UPDATE_Z = -2003,
    UPDATE_LOAD_SERVO = -2004,
    UPDATE_COVER_SERVO = -2005,

    @classmethod
    def is_member(cls, value):
        return value in cls._value2member_map_
