import dataclasses
from typing import List, Optional

from autotrainer.core import Offset3DTuple
from autotrainer.core.reach_event import ReachEvent

__all__ = [
    "intertrial_process",
    "intertrial_inference",
    "IntertrialResponse",
]

# NB: keep me up:
@dataclasses.dataclass
class IntertrialResponse:
    # NB: all 3 x/y/z are relative values here:
    rh_max_vp_list: List[Optional[Offset3DTuple]] = dataclasses.field(default_factory=list)
    # NB: some values can None if offset cannot be determined.

    reach_events: List[ReachEvent] = dataclasses.field(default_factory=list)
    # include both right and left hands events

    other_events: List[ReachEvent] = dataclasses.field(default_factory=list)
    # include other, non-hand based, events

    food_consumed: int = 0  # total pellets consumed during session/trial
    successful_reaches: int = 0  # whose these are successful reaches (Right-Hand)
    pellets_presented: int = 0  # there were that many total pellets presented.
        # NB: this is now discarded/not used anymore. Instead, we use the pellet-sent event to count the
        # pellets presented to animals.
    total_reaches: int = 0  # there were this many total reaches (both hands)

    def humanize(self, n_digits=2):
        rounded = dataclasses.replace(
            self,
            rh_max_vp_list=[None if o is None else o.round(n_digits) for o in self.rh_max_vp_list],
        )
        return repr(rounded)


# importing function/name from a module where the function name equals the module name imported from,
# creates slight issues with IDEs and eventual real import code.
from .intertrial_process import intertrial_process
from .intertrial_inference import intertrial_inference
# might need change this.
