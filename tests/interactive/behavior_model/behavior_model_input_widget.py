from PySide6.QtWidgets import QWidget, QGridLayout

from autotrainer.pyside import QSimpleGroupBox
from tests.interactive.behavior_model.behavior_model_head_fix_input_widget import BehaviorModelHeadFixInputWidget
from tools.acquisition.model.head_fix_model import HeadFixModel


class BehaviorModelInputWidget(QWidget):
    def __init__(self, head_fix: HeadFixModel):
        super().__init__()

        layout = QGridLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        self.head_fix = BehaviorModelHeadFixInputWidget(head_fix)
        layout.addWidget(QSimpleGroupBox("Head Fix State", self.head_fix), 0, 0)

        # self._cage_input = BehaviorModelCageInputWidget(cage_model)
        # layout.addWidget(QSimpleGroupBox("Cage State", self._cage_input), 0, 1)

        self.setLayout(layout)
