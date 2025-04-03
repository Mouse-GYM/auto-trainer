from enum import IntEnum, Enum


# Note: This also inherits from Enum and do not follow the Python underscore naming convention so they are presented in
# event logs and other output in the desired format without needing to custom format everywhere.

class GymDeviceEventKind(IntEnum, Enum):
    deviceCommandSend = 2001,
    deviceCommandAcknowledge = 2002
