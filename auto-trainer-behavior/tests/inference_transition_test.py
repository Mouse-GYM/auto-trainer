"""
Test transition behavior with explicit calls to the transitions and the behavior algorithm state only.  Transitions that
would/should happen due to external input (devices, pose information) are tested elsewhere.  These tests do not require
mocks or real interfaces.
"""
import logging

from autotrainer.behavior import InferenceMachine, InferenceState

logging.basicConfig(level=logging.DEBUG)
logging.getLogger('transitions').setLevel(logging.INFO)


def assert_load_cycle(machine: InferenceMachine, should_release: bool = True) -> None:
    """
    This is essentially the spec of what the behavior should be each time an ack is received from the real pellet device
    for a load->release cycle.  It defines what should happen in pellet_device_ack_received().  The state machine should
    pass tests using this, and then similarly pass when using an actual pellet device or mock.
    :param machine: InferenceMachine instance
    :param should_release: True if pellet release is expected (vs. remaining covered)
    :return: None
    """
    machine.load_pellet()

    assert machine.state == InferenceState.loading

    machine.send_pellet()

    assert machine.state == InferenceState.sending

    # When send completes, the machine transitions to covering in the ack that won't ever come in this testing.
    machine.state = InferenceState.covering

    machine.release_pellet()

    if should_release:
        assert machine.state == InferenceState.releasing

        machine.monitor_pellet()

        assert machine.state == InferenceState.monitoring
    else:
        assert machine.state == InferenceState.covering


def assert_covered_was_released(machine: InferenceMachine) -> None:
    """
    Verify that a covered pellet was release, which should also immediately transition to monitoring.
    :param machine: InferenceMachine instance
    :return: None
    """
    assert machine.state == InferenceState.releasing

    machine.monitor_pellet()

    assert machine.state == InferenceState.monitoring


def test_covered_load_cycle():
    machine = InferenceMachine()

    assert_load_cycle(machine, should_release=False)

    # Forcibly start a session for testing purposes.  This would normally occur at the system state level.
    machine.algorithm.start_session()

    # Should transition to releasing if session starts while covered.
    assert_covered_was_released(machine)

    machine.algorithm.end_session()

    # Should return to covered at end of session
    assert machine.state == InferenceState.covering

    machine.algorithm.start_session()

    assert_covered_was_released(machine)

    # Reload missing pellet from monitoring state.
    machine.pellet_lost()

    assert machine.state == InferenceState.missing

    assert_load_cycle(machine, should_release=True)

    machine.algorithm.end_session()

    assert machine.state == InferenceState.covering


def test_covered_disabled_load_cycle():
    machine = InferenceMachine()

    machine.algorithm.pellet_cover_enabled = False

    # With covering disabled, should go directly to release whether in session or not (i.e., in tunnel or not)
    assert_load_cycle(machine, should_release=True)


if __name__ == '__main__':
    test_covered_load_cycle()

    test_covered_disabled_load_cycle()
