from PySide6.QtWidgets import QWidget, QGridLayout

from tests.interactive.behavior_model.behavior_model_head_fix_input_widget import BehaviorModelHeadFixInputWidget
from tools.acquisition.model.head_fix_model import HeadFixModel


class BehaviorModelInputWidget(QWidget):
    def __init__(self, head_fix: HeadFixModel):
        super().__init__()

        layout = QGridLayout()

        self.head_fix = BehaviorModelHeadFixInputWidget(head_fix)

        layout.addWidget(self.head_fix, 0, 0)

        layout.addWidget(QWidget(), 0, 1)

        layout.setColumnStretch(1, 1)

        self.setLayout(layout)
