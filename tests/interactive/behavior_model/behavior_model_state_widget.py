from PySide6.QtWidgets import QWidget, QGridLayout, QLabel, QListWidget, QListWidgetItem, QVBoxLayout
from statemachine import State

from autotrainer.core import TriggerManager, CAPTURE_TRIGGER_ID
from tools.acquisition.behavior.behavior_model import BehaviorModel


class BehaviorModelStateWidget(QWidget):
    def __init__(self, model: BehaviorModel):
        super().__init__()

        model.add_listener(self)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 8, 0, 8)

        grid_layout = QGridLayout()
        grid_layout.setContentsMargins(8, 8, 8, 8)

        self.transition_list = QListWidget()
        grid_layout.addWidget(QLabel("Transitions"), 0, 0)
        grid_layout.addWidget(self.transition_list, 1, 0)

        self.event_list = QListWidget()
        grid_layout.addWidget(QLabel("Events"), 0, 1)
        grid_layout.addWidget(self.event_list, 1, 1)

        layout.addLayout(grid_layout, 1)

        self.setLayout(layout)

        TriggerManager.instance().register(self._trigger_received, CAPTURE_TRIGGER_ID)

    def after_transition(self, event: str, source: State, target: State):
        QListWidgetItem(f"{source.id}->({event})->{target.id}", self.transition_list)

    def _trigger_received(self, _sender, trigger_id, context):
        QListWidgetItem(f"{trigger_id} = {context}", self.event_list)
