from typing import Optional

from PySide6.QtWidgets import QLabel

import qtawesome as qta


class StatusIcon(QLabel):
    def __init__(self, on_icon: Optional[str] = None, off_icon: Optional[str] = None, on_color: str ="green",
                 off_color: str = "black", size: int = 18, parent=None):
        super(StatusIcon, self).__init__(parent)

        self._on = qta.icon(on_icon or 'fa5s.check-circle', color=on_color).pixmap(size, size)
        self._off = qta.icon(off_icon or 'fa5s.times-circle', color=off_color).pixmap(size, size)

        self.setStatus(False)

    def setStatus(self, status: bool):
        self.setPixmap(self._on if status else self._off)

    @staticmethod
    def alarmIcon(size: int = 18, parent=None):
        return StatusIcon(on_icon='fa5s.bell', off_icon='fa5s.bell', on_color='red', off_color='gray', size=size,
                          parent=parent)

    @staticmethod
    def alarmIcon2(size: int = 18, parent=None):
        return StatusIcon(on_icon='fa5s.bell', off_icon='fa5.bell', on_color='red', off_color='gray', size=size,
                          parent=parent)

    @staticmethod
    def doorIcon(size: int = 18, parent=None):
        return StatusIcon(on_icon='fa5s.door-open', off_icon='fa5s.door-closed', on_color='red', off_color='black',
                          size=size, parent=parent)
