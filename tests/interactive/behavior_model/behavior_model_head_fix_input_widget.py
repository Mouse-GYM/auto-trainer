from PySide6.QtWidgets import QWidget, QFormLayout

from autotrainer.pyside import QSwitch
from tools.acquisition.model.head_fix_model import HeadFixModel


class BehaviorModelHeadFixInputWidget(QWidget):
    def __init__(self, head_fix: HeadFixModel):
        super().__init__()

        self._head_fix = head_fix

        layout = QFormLayout()

        self.load_cell_engaged = QSwitch()
        layout.addRow("Load cell engaged:", self.load_cell_engaged)

        self.headbar_engaged = QSwitch()
        layout.addRow("Headbar engaged:", self.headbar_engaged)

        self.force_detector_engaged = QSwitch()
        layout.addRow("Force detector engaged:", self.force_detector_engaged)

        self.setLayout(layout)

        self._connect_signals()

    def _connect_signals(self):
        def set_is_load_cell_engaged(x: int):
            self._head_fix.is_load_cell_engaged = x != 0

        self.load_cell_engaged.stateChanged.connect(set_is_load_cell_engaged)

        def set_is_headbar_engaged(x: int):
            self._head_fix.is_headbar_engaged = x != 0

        self.headbar_engaged.stateChanged.connect(set_is_headbar_engaged)

        def set_is_force_detector_engaged(x: int):
            self._head_fix.is_force_detector_engaged = x != 0

        self.force_detector_engaged.stateChanged.connect(set_is_force_detector_engaged)
