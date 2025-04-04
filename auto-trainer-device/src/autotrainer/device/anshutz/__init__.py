import typing

from .head_fix import HeadFix, parse_measurements, parse_measurement
from .pellet_delivery import PelletDelivery
from .serial_interface import SerialInterface


def get_available_hardware() -> typing.List[str]:
    return SerialInterface.refresh_ports()
