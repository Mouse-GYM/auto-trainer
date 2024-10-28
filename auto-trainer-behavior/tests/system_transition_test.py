import logging

import pytest
from transitions import MachineError

from autotrainer.behavior import SystemMachine, SystemState, BehaviorAlgorithm, BehaviorLimits

logging.basicConfig(level=logging.DEBUG)
logging.getLogger('transitions').setLevel(logging.INFO)


def test_constructor():
    model = SystemMachine(algorithm=BehaviorAlgorithm(BehaviorLimits(pellet_missing_time=0.1)))

    assert model.algorithm.limits.pellet_missing_time == 0.1


def test_behavior_transitions():
    """Tests transition behavior with explicit calls to the transitions"""
    model = SystemMachine(None, None, None, None, None)

    assert model.state == SystemState.cage

    with pytest.raises(MachineError):
        model.exit_intersession()

    with pytest.raises(MachineError):
        model.exit_tunnel()

    model.enter_tunnel()

    assert model.state == SystemState.tunnel

    with pytest.raises(MachineError):
        model.enter_intersession()

    with pytest.raises(MachineError):
        model.exit_intersession()

    model.exit_tunnel()

    assert model.state == SystemState.cage

    model.enter_intersession()

    assert model.state == SystemState.intersession

    with pytest.raises(MachineError):
        model.enter_tunnel()

    with pytest.raises(MachineError):
        model.exit_tunnel()

    model.exit_intersession()

    assert model.state == SystemState.cage


if __name__ == '__main__':
    test_constructor()

    test_behavior_transitions()
