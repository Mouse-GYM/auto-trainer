from enum import Enum


class PelletState(str, Enum):
    monitoring = "monitoring"
    loading = "loading"
    sending = "sending"
    releasing = "releasing"
    covering = "covering"
    home = "home"
    retract = "retract"
