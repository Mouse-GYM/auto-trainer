"""
Test transition behavior with explicit calls to the transitions and the behavior algorithm state only.  Transitions that
would/should happen due to external input (devices, pose information) are tested elsewhere.  These tests do not require
mocks or real interfaces.
"""
import logging
from functools import partial

from autotrainer.behavior import PelletMachine, PelletState
from .conftest import on_state_changed


logging.basicConfig(level=logging.DEBUG)
logging.getLogger('transitions').setLevel(logging.INFO)


def assert_load_cycle(machine: PelletMachine, should_release: bool = True) -> None:
    """
    This is essentially the spec of what the behavior should be each time an ack is received from the real pellet device
    for a load->release cycle.  It defines what should happen in pellet_device_ack_received().  The state machine should
    pass tests using this, and then similarly pass when using an actual pellet device or mock.
    :param machine: InferenceMachine instance
    :param should_release: True if pellet release is expected (vs. remaining covered)
    :return: None
    """
    machine.load_pellet()

    assert machine.state == PelletState.loading

    machine.send_pellet()

    assert machine.state == PelletState.sending

    # When send completes, the machine transitions to covering in the ack that won't ever come in this testing.
    machine.state = PelletState.covering

    machine.release_pellet()

    if should_release:
        assert machine.state == PelletState.releasing

        machine.monitor_pellet()

        assert machine.state == PelletState.monitoring
    else:
        assert machine.state == PelletState.covering


def assert_covered_was_released(machine: PelletMachine) -> None:
    """
    Verify that a covered pellet was release, which should also immediately transition to monitoring.
    :param machine: InferenceMachine instance
    :return: None
    """
    assert machine.state == PelletState.releasing

    machine.monitor_pellet()

    assert machine.state == PelletState.monitoring


def test_covered_load_cycle():
    machine = PelletMachine()

    assert_load_cycle(machine, should_release=False)

    # Forcibly start a session for testing purposes.  This would normally occur at the system state level.
    machine.algorithm.start_session()

    # Should transition to releasing if session starts while covered.
    assert_covered_was_released(machine)

    machine.algorithm.end_session()

    # Should return to covered at end of session
    assert machine.state == PelletState.covering

    machine.algorithm.start_session()

    assert_covered_was_released(machine)

    assert machine.state == PelletState.monitoring

    assert_load_cycle(machine, should_release=True)

    machine.algorithm.end_session()

    assert machine.state == PelletState.covering


def test_covered_disabled_load_cycle():
    machine = PelletMachine()

    state_transitions = []

    machine.events.state_changed += partial(on_state_changed, state_transitions=state_transitions)

    machine.algorithm.pellet_cover_enabled = False

    # With covering disabled, should go directly to release whether in session or not (i.e., in tunnel or not)
    assert_load_cycle(machine, should_release=True)
    assert state_transitions == [
        PelletState.loading,
        PelletState.sending,
        PelletState.covering,
        PelletState.releasing,
        PelletState.monitoring,
    ]


if __name__ == '__main__':
    test_covered_load_cycle()
    test_covered_disabled_load_cycle()
