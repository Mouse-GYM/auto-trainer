import logging

from autotrainer.behavior import BehaviorAlgorithm, BehaviorLimits, InferenceMachine, InferenceState

logging.basicConfig(level=logging.DEBUG)
logging.getLogger('transitions').setLevel(logging.INFO)


def test_inference_transitions():
    """Tests transition behavior with explicit calls to the transitions"""
    algorithm = BehaviorAlgorithm(BehaviorLimits())

    model = InferenceMachine(algorithm, None, None, None)

    assert model.state == InferenceState.missing

    model.load_pellet()

    assert model.state == InferenceState.loading

    model.send_pellet()

    assert model.state == InferenceState.sending

    # Simulate what happens when an actual send command completes.
    model.state = InferenceState.covering

    model.release_pellet()

    # Should not have worked if not in tunnel.

    assert model.state == InferenceState.covering

    # Have to forcibly enter tunnel and start a session for testing purposes.
    algorithm.start_session()
    model.before_enter_tunnel()

    # Should transition to releasing if tunnel entered while covered.

    assert model.state == InferenceState.releasing

    model.monitor_pellet()

    assert model.state == InferenceState.monitoring

    model.pellet_lost()

    assert model.state == InferenceState.missing

    # Reload while in tunnel.  These transitions happen automatically when the state machine has access to pellet
    # commands.
    model.load_pellet()
    model.send_pellet()
    model.state = InferenceState.covering
    model.release_pellet()
    model.monitor_pellet()

    assert model.state == InferenceState.monitoring

    # Leaving should attempt to cover.

    model.after_exit_tunnel()

    assert model.state == InferenceState.covering


if __name__ == '__main__':
    test_inference_transitions()
