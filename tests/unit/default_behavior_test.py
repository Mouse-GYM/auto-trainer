import logging

from tools.acquisition.behavior.behavior_model_transitions import BehaviorModelTransitions, SystemStates

logging.basicConfig(level=logging.DEBUG)
logging.getLogger('transitions').setLevel(logging.INFO)


def test_default_transitions():
    model = BehaviorModelTransitions(None)

    assert model.state == SystemStates.InCage

    model.enter_tunnel()
