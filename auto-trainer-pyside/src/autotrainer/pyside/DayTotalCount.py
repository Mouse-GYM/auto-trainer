from typing import Optional

from PySide6.QtWidgets import QLabel

_unprovided = object()  # sentinel


class DailyAndTotalCountsLabel(QLabel):

    def __init__(self, parent=None, *, day: Optional[int] = None, total: Optional[int] = None):
        super().__init__(parent)
        self._day_count = day
        self._total_count = total
        self.update_values()

    def update_values(self, day=_unprovided, total=_unprovided):
        if day is not _unprovided:
            self._day_count = day
        if total is not _unprovided:
            self._total_count = total
        day = self._day_count
        total = self._total_count
        self.setText(f"{'na' if day is None else day} / {'na' if total is None else total}")
