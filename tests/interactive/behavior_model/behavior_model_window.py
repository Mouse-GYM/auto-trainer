from PySide6 import QtGui
from PySide6.QtWidgets import QMainWindow, QWidget, QGridLayout, QStatusBar, QLabel
from statemachine import State

from autotrainer.pyside import QSimpleGroupBox
from tests.interactive.behavior_model.behavior_model_property_widget import BehaviorModelPropertyWidget
from tests.interactive.behavior_model.behavior_model_state_widget import BehaviorModelStateWidget

from tests.interactive.behavior_model.behavior_model_input_widget import BehaviorModelInputWidget
from autotrainer.behavior import BehaviorModel
from tools.acquisition.model.head_fix_model import HeadFixModel


class StateListener:
    def __init__(self, label: QLabel):
        self._label = label

    def on_enter_state(self, target: State, event):
        self._label.setText(target.name)


class BehaviorModelWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.head_fix_model = HeadFixModel()

        self.behavior_model = BehaviorModel(self.head_fix_model.head_fix_reader)

        self.setWindowTitle("Behavior Model Testing")
        self.setMinimumWidth(800)
        self.setMinimumHeight(600)

        widget = QWidget()

        layout = QGridLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        self.property_panel = BehaviorModelPropertyWidget(self.behavior_model.properties)
        layout.addWidget(QSimpleGroupBox("Model Properties", self.property_panel), 0, 0)

        self.input_panel = BehaviorModelInputWidget(self.head_fix_model)
        layout.addWidget(self.input_panel, 0, 1)

        self.output_panel = BehaviorModelStateWidget(self.behavior_model)
        layout.addWidget(self.output_panel, 2, 0, 1, 2)

        widget.setLayout(layout)

        self.setCentralWidget(widget)

        self._configure_statusbar()

        self.behavior_model.add_listener(self)

    def on_enter_state(self, target: State, event):
        self._status_label.setText(target.name)

    def _configure_statusbar(self):
        self._status_bar = QStatusBar(self)

        current_font = QtGui.QFont()
        current_font.setBold(True)

        label = QLabel("System: ")
        label.setFont(current_font)
        self._status_bar.addWidget(label)
        self._status_label = QLabel(self.behavior_model.current_state.name)
        self._status_bar.addWidget(self._status_label)

        self.setStatusBar(self._status_bar)
