from PySide6 import QtGui
from PySide6.QtWidgets import QMainWindow, QWidget, QGridLayout, QStatusBar, QLabel
from statemachine import State

from autotrainer.pyside import ATSeparator
from tests.interactive.behavior_model.behavior_model_state_widget import BehaviorModelStateWidget

from tests.interactive.behavior_model.behavior_model_input_widget import BehaviorModelInputWidget
from tools.acquisition.behavior.behavior_model import BehaviorModel
from tools.acquisition.model.head_fix_model import HeadFixModel


class BehaviorModelWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.head_fix_model = HeadFixModel()

        self.behavior_model = BehaviorModel(self.head_fix_model)

        self.setWindowTitle("Behavior Model Testing")

        widget = QWidget()

        layout = QGridLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        self.input_panel = BehaviorModelInputWidget(self.head_fix_model)

        layout.addWidget(self.input_panel, 0, 0)

        layout.addWidget(ATSeparator(), 1, 0)

        self.output_panel = BehaviorModelStateWidget(self.behavior_model)

        layout.addWidget(self.output_panel, 2, 0)

        widget.setLayout(layout)

        self.setCentralWidget(widget)

        self._configure_statusbar()

        self.behavior_model.add_listener(self)

    def on_enter_state(self, target: State, event):
        self._status_label.setText(f"State: {target.name}")

    def _configure_statusbar(self):
        current_font = QtGui.QFont()
        current_font.setBold(True)
        self._status_label = QLabel(f"State: {self.behavior_model.current_state.name}")
        self._status_label.setFont(current_font)
        self._status_bar = QStatusBar(self)
        self._status_bar.addWidget(self._status_label)
        self.setStatusBar(self._status_bar)
