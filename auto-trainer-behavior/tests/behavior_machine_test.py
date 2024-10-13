import logging

from autotrainer.behavior import SystemState

from mocks import BehaviorMachineWithMocks

logging.basicConfig(level=logging.DEBUG)
logging.getLogger('transitions').setLevel(logging.INFO)


def test_pellet_behavior():
    """Tests transition behavior using input from pellet changes and commands"""
    model = BehaviorMachineWithMocks()

    assert model.state == SystemState.cage

    model.headfix.is_load_cell_engaged = True

    assert model.state == SystemState.tunnel

    model.headfix.is_load_cell_engaged = False

    assert model.state == SystemState.cage


if __name__ == '__main__':
    test_pellet_behavior()
