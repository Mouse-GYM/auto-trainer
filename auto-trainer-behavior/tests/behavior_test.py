import logging

from autotrainer.behavior import BehaviorModel, SystemStates, PelletDeliveryStates

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

    assert model.state == SystemStates.cage

    mock_headfix.is_load_cell_engaged = True

    assert model.state == PelletDeliveryStates.monitoring

    mock_pose.send_response(False)

    assert model.state == PelletDeliveryStates.loading

    mock_pellet.send_ack()

    assert model.state == PelletDeliveryStates.sending

    mock_pellet.send_ack()

    assert model.state == PelletDeliveryStates.releasing

    mock_pellet.send_ack()

    assert model.state == PelletDeliveryStates.monitoring

    mock_headfix.is_load_cell_engaged = False

    assert model.state == SystemStates.cage


if __name__ == '__main__':
    test_pellet_behavior()
