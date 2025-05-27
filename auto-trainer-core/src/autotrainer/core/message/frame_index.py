import enum


class FrameIndexCategory(enum.IntEnum):

    SWITCH_TO_ONLINE = -6
    SWITCH_TO_OFFLINE_MODE = -5
    PADDING = -4
    EOF_OFFLINE_PROCESSING = -3
    EOF_RECORDING = -2

    ONLINE_NO_RECORDING = -1  # NB: DO NOT CHANGE VALUE OF THIS ONE

    RECORDING_OR_OFFLINE_PROCESSING = 1
    # NB: positive or zero frane index means recording online or offline reprocessing.

    @classmethod
    def _missing_(cls, value: int):
        if isinstance(value, str):
            value = int(value)
        if isinstance(value, float):
            v = int(value)
            if v != value:
                return super()._missing_(value)
            value = v
        if value >= 0:
            return FrameIndexCategory.RECORDING_OR_OFFLINE_PROCESSING
        if value == -1:
            return FrameIndexCategory.ONLINE_NO_RECORDING
        if value == -2:
            return FrameIndexCategory.EOF_RECORDING
        return super()._missing_(value)
