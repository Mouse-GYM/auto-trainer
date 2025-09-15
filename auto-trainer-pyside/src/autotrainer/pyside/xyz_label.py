
import math
from typing import Optional

from PySide6.QtWidgets import QLabel

from autotrainer.core import Offset3DTuple



class XYZQLabel(QLabel):
    """An XYZ offset/position label"""

    def __init__(self):
        self._xyz_values = Offset3DTuple(math.nan, math.nan, math.nan)
        super().__init__(self.xyz_to_str(self._xyz_values))

    def update_coordinate(self, xyz: Optional[Offset3DTuple], *, x=None, y=None, z=None):
        if xyz is not None and (x is not None or y is not None or z is not None):
            raise TypeError("Only accept xyz or x/y/z separated. not both")
        if x is None and y is None and z is None:
            if xyz is None:
                xyz = math.nan, math.nan, math.nan
            x, y, z = xyz
        self._xyz_values = self._xyz_values.replace(x=x, y=y, z=z)
        self.setText(self.xyz_to_str(self._xyz_values))

    @staticmethod
    def xyz_to_str(xyz: Offset3DTuple, *, digit_precision: int = 2):
        return "/".join("na" if (math.isnan(v) or v is None) else f"{v:.0{digit_precision}f}" for v in xyz)
