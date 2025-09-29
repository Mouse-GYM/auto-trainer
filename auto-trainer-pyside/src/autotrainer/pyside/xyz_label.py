
import math
from typing import Optional

from PySide6.QtWidgets import QLabel

from autotrainer.core import Offset3DTuple


NO_UPDATES = "(no updates)"


class XYZQLabel(QLabel):
    """An XYZ offset/position label"""

    def __init__(self, start_value: str = NO_UPDATES, *, n_digits: int = 1):
        self._xyz_values = Offset3DTuple(math.nan, math.nan, math.nan)
        self._n_digits = n_digits
        super().__init__(start_value)

    def update_coordinate(
        self,
        xyz: Optional[Offset3DTuple] = None,
        *,
        x: Optional[float]=None,
        y: Optional[float]=None,
        z: Optional[float]=None,
    ):
        if xyz is not None and (x is not None or y is not None or z is not None):
            raise TypeError("Only accept xyz or x/y/z separated. not both")
        if x is None and y is None and z is None:
            if xyz is None:
                xyz = math.nan, math.nan, math.nan
            x, y, z = xyz
        self._xyz_values = self._xyz_values.replace(x=x, y=y, z=z)
        self.setText(self.xyz_to_str(self._xyz_values, n_digits=self._n_digits))

    @staticmethod
    def xyz_to_str(xyz: Offset3DTuple, *, n_digits: int = 1):
        return " / ".join("na" if (math.isnan(v) or v is None)
                          else f"{v:.0{n_digits}f}"
                          for v in xyz)
