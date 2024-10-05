from enum import Enum

from transitions.extensions import HierarchicalMachine


class SystemStates(str, Enum):
    cage = "cage"


class PelletDeliveryStates(str, Enum):
    monitoring = "monitoring",
    loading = "loading"
    sending = "sending"
    releasing = "releasing"


PelletDeliveryStateDefinition = {"name": "pellet", "initial": PelletDeliveryStates.monitoring,
                                 "children": [e for e in PelletDeliveryStates]}


class BehaviorModelBaseModel:
    states = [e for e in SystemStates] + [PelletDeliveryStateDefinition]

    transitions = [
        {"trigger": "enter_tunnel", "source": "*", "dest": PelletDeliveryStates.monitoring,
         "before": "before_enter_tunnel"},
        {"trigger": "exit_tunnel", "source": "*", "dest": SystemStates.cage,
         "after": "after_exit_tunnel"},
        {"trigger": "my_load_pellet", "source": PelletDeliveryStates.monitoring,
         "dest": PelletDeliveryStates.loading, "before": "before_load_pellet"},
        {"trigger": "send_pellet", "source": PelletDeliveryStates.loading,
         "dest": PelletDeliveryStates.sending, "before": "before_send_pellet"},
        {"trigger": "release_pellet", "source": PelletDeliveryStates.sending,
         "dest": PelletDeliveryStates.releasing, "before": "before_release_pellet",
         "after": "after_release_pellet"},
        {"trigger": "monitor_pellet", "source": PelletDeliveryStates.releasing,
         "dest": PelletDeliveryStates.monitoring}
    ]

    def __init__(self):
        self.state = SystemStates.cage

        self.machine = HierarchicalMachine(model=self, states=BehaviorModelBaseModel.states,
                                           transitions=BehaviorModelBaseModel.transitions, auto_transitions=False,
                                           initial=SystemStates.cage, model_override=True)

    def enter_tunnel(self):
        pass

    def may_enter_tunnel(self):
        pass

    def exit_tunnel(self):
        pass

    def may_exit_tunnel(self):
        pass

    def trigger(self):
        pass

    def may_trigger(self):
        pass

    def my_load_pellet(self):
        pass

    def may_my_load_pellet(self):
        pass

    def send_pellet(self):
        pass

    def may_send_pellet(self):
        pass

    def release_pellet(self):
        pass

    def may_release_pellet(self):
        pass

    def monitor_pellet(self):
        pass

    def may_monitor_pellet(self):
        pass

    def is_cage(self):
        pass

    def is_pellet(self):
        pass

    def is_pellet_monitoring(self):
        pass

    def is_pellet_loading(self):
        pass

    def is_pellet_sending(self):
        pass

    def is_pellet_releasing(self):
        pass
