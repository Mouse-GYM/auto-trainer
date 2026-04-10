import dataclasses
from dataclasses import dataclass
from typing import List, Dict, Any

from autotrainer.core import Offset3DTuple


@dataclass
class ReachEvent:
    init: int  # frame index
    end: int  # frame index
    max: int = -1  # frame index
    method: str = 'none'  # none, right_hand, left_hand, tongue
    outcome: str = 'none'  # none, stalled, missed, dropped, grabbed, eaten
    delay_since_presented: float = 0  # is basically: init / fps


@dataclass
class IntersessionResponse:
    # NB: all 3 x/y/z are relative values here:
    rh_max_vp_list: List[Offset3DTuple] = dataclasses.field(default_factory=list)

    reach_events: List[ReachEvent] = dataclasses.field(default_factory=list)
    other_events: List[ReachEvent] = dataclasses.field(default_factory=list)

    food_consumed: int = 0  # total pellets consumed during session/trial
    successful_reaches: int = 0  # whose these are successful reaches (Right-Hand)
    pellets_presented: int = 0  # there were that many total pellets presented.
        # NB: this is now discarded/not used anymore. Instead, we use the pellet-sent event to count the
        # pellets presented to animals.
    total_reaches: int = 0  # there were this many total reaches (both hands)

    def humanize(self, n_digits=2):
        rounded = dataclasses.replace(
            self,
            rh_max_vp_list=[o.round(n_digits) for o in self.rh_max_vp_list],
        )
        return repr(rounded)


# importing function/name from a module where the function name equals the module name imported from,
# creates slight issues with IDEs and eventual real import code.
from .intersession_process import intersession_process
from .intersession_inference import intersession_inference
# might need change this.

