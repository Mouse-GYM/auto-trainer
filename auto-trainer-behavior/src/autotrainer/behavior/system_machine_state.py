from enum import Enum


class SystemState(str, Enum):
    cage = "cage",
    tunnel = "tunnel",
    intersession = "intersession"
