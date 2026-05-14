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

    @classmethod
    def from_version_zero(cls, content: dict) -> Self:
        configuration = cls()

        if "head_fix" in content:
            configuration.tunnel_identifier = content["head_fix"].get("port", "")
        if "pellet_delivery" in content:
            configuration.pellet_identifier = content["pellet_delivery"].get("port", "")

        return configuration


hardware_configuration_representer = make_camelize_representer("!HardwareConfiguration")
hardware_configuration_constructor = make_decamelize_constructor(HardwareConfiguration)
