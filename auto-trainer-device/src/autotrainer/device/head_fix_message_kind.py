from enum import IntEnum


class HeadFixMessageKind(IntEnum):
    RAW_COMMAND = 1,
    MEASUREMENT = -101,  # Deprecated
    SET_MAGNET_INTENSITY = 3,
    SETTINGS = 4,
    UPDATE_SCALE_TARE = 5,
    STREAM_START = 6,
    STREAM_STOP = 7,

    UPDATE_MAGNET = -1100,  # Deprecated
    AUDIO_DATA = -1101,  # Deprecated
