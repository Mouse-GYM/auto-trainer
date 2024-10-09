import logging

from autotrainer.behavior import BehaviorModel, SystemState

from mocks import MockHeadfixReader
from mocks import MockPelletDelivery
from mocks import MockPoseAlgorithm

logging.basicConfig(level=logging.DEBUG)
logging.getLogger('transitions').setLevel(logging.INFO)


def test_pellet_behavior():
    """Tests transition behavior using input from pellet changes and commands"""
    mock_headfix = MockHeadfixReader()
    mock_pellet = MockPelletDelivery()
    mock_pose = MockPoseAlgorithm()

    model = BehaviorModel(mock_headfix, mock_pellet, mock_pellet, mock_pose)

    assert model.state == SystemState.cage

    mock_headfix.is_load_cell_engaged = True

    assert model.state == SystemState.tunnel

    mock_headfix.is_load_cell_engaged = False

    assert model.state == SystemState.cage


if __name__ == '__main__':
    test_pellet_behavior()
