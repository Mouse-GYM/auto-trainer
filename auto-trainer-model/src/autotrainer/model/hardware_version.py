from enum import IntEnum

from autotrainer.device import HAVE_CAN_DEVICE


class HardwareVersion(IntEnum):
    """
    Allow applications to identify hardware versions without knowing the specific techniques, function calls, or
    properties to make that identification.
    """
    UNKNOWN = 0
    ANSHUTZ = 1
    ALOGUS_V1 = 2

    def __str__(self):
        if self == HardwareVersion.ANSHUTZ:
            return "Anschutz"
        elif self == HardwareVersion.ALOGUS_V1:
            return "Alogus v1"
        else:
            return "Unknown"


def default_determine_hardware_version() -> HardwareVersion:
    """
    Determine the hardware version of the device.

    :return: The `HardwareVersion` of the device.
    """
    if HAVE_CAN_DEVICE:
        return HardwareVersion.ALOGUS_V1
    else:
        return HardwareVersion.ANSHUTZ
