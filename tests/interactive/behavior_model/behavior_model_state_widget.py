from PySide6.QtWidgets import QWidget, QGridLayout, QLabel, QListWidget, QListWidgetItem, QVBoxLayout
from statemachine import State

from autotrainer.core import TriggerManager, CAPTURE_TRIGGER_ID
from autotrainer.pyside import QSimpleGroupBox
from tools.acquisition.behavior.behavior_model import BehaviorModel


class TransitionListener:
    def __init__(self, name: str, widget: QListWidget):
        self.name = name
        self.widget = widget

    def after_transition(self, event: str, source: State, target: State):
        QListWidgetItem(f"{self.name}: {source.id}->({event})->{target.id}", self.widget)


class BehaviorModelStateWidget(QWidget):
    def __init__(self, model: BehaviorModel):
        super().__init__()

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 8, 0, 8)

        grid_layout = QGridLayout()
        grid_layout.setContentsMargins(8, 8, 8, 8)

        self.transition_list = QListWidget()
        grid_layout.addWidget(QSimpleGroupBox("State Transitions", self.transition_list), 0, 0)

        self.event_list = QListWidget()
        grid_layout.addWidget(QSimpleGroupBox("Behavior Events", self.event_list), 0, 1)

        layout.addLayout(grid_layout, 1)

        self.setLayout(layout)

        model.add_listener(self)
        # model.cage_model.add_listener(TransitionListener("Cage", self.transition_list))

        TriggerManager.instance().register(self._trigger_received, CAPTURE_TRIGGER_ID)

    def after_transition(self, event: str, source: State, target: State):
        QListWidgetItem(f"System: {source.id}->({event})->{target.id}", self.transition_list)

    def _trigger_received(self, _sender, trigger_id, context):
        QListWidgetItem(f"{trigger_id} = {context}", self.event_list)
