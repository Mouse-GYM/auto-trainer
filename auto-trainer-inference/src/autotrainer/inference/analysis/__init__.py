
from dataclasses import dataclass


@dataclass
class IntersessionResponse:
    # NB: all 3 x/y/z are relative values here:
    pellet_x: float = 0
    pellet_y: float = 0
    pellet_z: float = 0
    food_consumed: int = 0
    successful_reaches: int = 0
    pellets_presented: int = 0


# importing function/name from a module where the function name equals the module name imported from,
# creates slight issues with IDEs and eventual real import code.
from .intersession_process import intersession_process
from .intersession_inference import intersession_inference
# might need change this.

