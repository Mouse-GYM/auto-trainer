import dataclasses
from dataclasses import dataclass
from typing import List

from autotrainer.core import Offset3DTuple


@dataclass
class IntersessionResponse:
    # NB: all 3 x/y/z are relative values here:
    pellet_x: float = 0
    pellet_y: float = 0
    pellet_z: float = 0

    all_shifts: List[Offset3DTuple] = dataclasses.field(default_factory=list)

    food_consumed: int = 0  # total pellets consumed during session/trial
    successful_reaches: int = 0  # whose these are successful reaches (Right-Hand)
    pellets_presented: int = 0  # there were that many total pellets presented
    total_reaches: int = 0  # there were this many total reaches (both hands)

    def humanize(self, n_digits=2):
        rounded = dataclasses.replace(
            self,
            pellet_x=round(self.pellet_x, n_digits),
            pellet_y=round(self.pellet_y, n_digits),
            pellet_z=round(self.pellet_z, n_digits),
        )
        return repr(rounded)


# importing function/name from a module where the function name equals the module name imported from,
# creates slight issues with IDEs and eventual real import code.
from .intersession_process import intersession_process
from .intersession_inference import intersession_inference
# might need change this.

