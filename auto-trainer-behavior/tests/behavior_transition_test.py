import logging

from autotrainer.behavior import BehaviorModel, SystemState

logging.basicConfig(level=logging.DEBUG)
logging.getLogger('transitions').setLevel(logging.INFO)


def test_behavior_transitions():
    """Tests transition behavior with explicit calls to the transitions"""
    model = BehaviorModel(None, None, None, None)

    assert model.state == SystemState.cage

    model.enter_tunnel()

    assert model.state == SystemState.tunnel

    model.exit_tunnel()

    assert model.state == SystemState.cage


if __name__ == '__main__':
    test_behavior_transitions()
