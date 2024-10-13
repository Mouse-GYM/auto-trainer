import logging

from autotrainer.behavior import BehaviorAlgorithm, BehaviorLimits, InferenceBehaviorMachine, InferenceState

logging.basicConfig(level=logging.DEBUG)
logging.getLogger('transitions').setLevel(logging.INFO)


def test_inference_transitions():
    """Tests transition behavior with explicit calls to the transitions"""
    properties = BehaviorAlgorithm(BehaviorLimits())

    model = InferenceBehaviorMachine(properties, None, None, None)

    assert model.state == InferenceState.monitoring

    model.load_pellet()

    assert model.state == InferenceState.loading

    model.send_pellet()

    assert model.state == InferenceState.sending

    model.release_pellet()

    assert model.state == InferenceState.releasing

    model.monitor_pellet()

    assert model.state == InferenceState.monitoring


if __name__ == '__main__':
    test_inference_transitions()
