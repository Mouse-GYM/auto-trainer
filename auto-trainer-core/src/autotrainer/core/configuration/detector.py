import dataclasses
from typing import Optional


@dataclasses.dataclass
class DetectorConfig:

    def __new__(cls, *args, **kwargs):  # force only kwargs for all detector based configs
        if len(args) > 0:
            raise TypeError(f"{cls.__name__}.__init__() takes 1 positional argument but {1 + len(args)} were given")
        # NB: kwargs are consumed by dataclass __init__ generated method.
        return super().__new__(cls)


@dataclasses.dataclass
class GroupSubDetectorConfig(DetectorConfig):

    use: bool = True  # allow to "enable/disable" a sub-detector
    # decide if the sub-detector is participating in the activation of the is_engaged of the parent/group detector.

    allow_autoresume_on_cleared: bool = True
    # decide if, when the sub-detector is_engaged is cleared, it really is participating in the disengage
    # of the parent/group detector.
    # i.e: if this is False and the sub-detect had engaged,
    # then the parent/group detector is_engaged will be kept engaged.
    # A restart of this one, or explicit unset of its is_engaged, will be needed to clear it.
    # Or an update of the allow_autoresume_on_cleared of the sub-detector to True,
    # or unregistering it from the parent/group detector.
