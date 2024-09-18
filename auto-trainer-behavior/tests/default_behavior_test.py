import logging

from autotrainer.behavior import BehaviorModel, SystemStates

logging.basicConfig(level=logging.DEBUG)
logging.getLogger('transitions').setLevel(logging.INFO)


def test_default_transitions():
    model = BehaviorModel(None, None)

    assert model.state == SystemStates.InCage

    model.enter_tunnel()
