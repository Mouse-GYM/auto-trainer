from enum import IntEnum, Enum


class GymDeviceEventKind(IntEnum, Enum):
    deviceCommandSend = 2001,
    deviceCommandAcknowledge = 2002
