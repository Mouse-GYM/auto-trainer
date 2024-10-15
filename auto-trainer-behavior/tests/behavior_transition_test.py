import logging

from autotrainer.behavior import SystemBehaviorMachine, SystemState, BehaviorAlgorithm, BehaviorLimits

logging.basicConfig(level=logging.DEBUG)
logging.getLogger('transitions').setLevel(logging.INFO)


def test_constructor():
    model = SystemBehaviorMachine(algorithm=BehaviorAlgorithm(BehaviorLimits(pellet_missing_time=0.1)))

    assert model.algorithm.limits.pellet_missing_time == 0.1


def test_behavior_transitions():
    """Tests transition behavior with explicit calls to the transitions"""
    model = SystemBehaviorMachine(None, None, None, None, None)

    assert model.state == SystemState.cage

    model.enter_tunnel()

    assert model.state == SystemState.tunnel

    model.exit_tunnel()

    assert model.state == SystemState.cage


if __name__ == '__main__':
    test_constructor()

    test_behavior_transitions()
