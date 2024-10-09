import logging

from autotrainer.behavior import BehaviorProperties, BehaviorLimits, InferenceBehaviorModel, InferenceState

from mocks import MockPelletDelivery
from mocks import MockPoseAlgorithm

logging.basicConfig(level=logging.DEBUG)
logging.getLogger('transitions').setLevel(logging.INFO)


def test_inference_behavior():
    """Tests transition behavior using input from pellet changes and commands"""
    mock_pellet = MockPelletDelivery()
    mock_pose = MockPoseAlgorithm()

    properties = BehaviorProperties(BehaviorLimits())

    model = InferenceBehaviorModel(properties, mock_pellet, mock_pellet, mock_pose)

    assert model.state == InferenceState.monitoring

    mock_pose.send_response(False, False)

    assert model.state == InferenceState.loading

    mock_pellet.send_ack()

    assert model.state == InferenceState.sending

    mock_pellet.send_ack()

    assert model.state == InferenceState.releasing

    mock_pellet.send_ack()

    assert model.state == InferenceState.monitoring


if __name__ == '__main__':
    test_inference_behavior()
