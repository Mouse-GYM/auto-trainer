from dataclasses import dataclass

from typing import Optional
from typing_extensions import Self


from autotrainer.core import make_camelize_representer, make_decamelize_constructor


@dataclass
class HardwareConfiguration:
    tunnel_identifier: str = ""
    pellet_identifier: str = ""

    min_ack_timeout: Optional[float] = None  # min device-ack-timeout
    """CAN uuid ACK timeout, if not set here then default code value of 3s is used."""

    board_status_timeout: Optional[float] = None
    """If any of the boards sub-device misses its status message for more than this delay -> system fault.
    If not set here then default code value of 15s is used.
    """

    camera_start_timeout: float = 5
    """Delay to wait, in seconds, for a camera to be confirmed running once it is started.
    If it isn't confirmed within that delay: an error will be set/raised by the correspond code.
    """

    def __post_init__(self):
        if self.camera_start_timeout <= 0:
            raise ValueError(f"camera_start_timeout negative or zero: {self.camera_start_timeout}")

    @classmethod
    def from_version_zero(cls, content: dict) -> Self:
        configuration = cls()

        if "head_fix" in content:
            configuration.tunnel_identifier = content["head_fix"].get("port", "")
        if "pellet_delivery" in content:
            configuration.pellet_identifier = content["pellet_delivery"].get("port", "")

        return configuration
