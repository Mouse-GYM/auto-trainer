"""
Test transition behavior with explicit calls to the transitions and the behavior algorithm state only.  Transitions that
would/should happen due to external input (devices, pose information) are tested elsewhere.  These tests do not require
mocks or real interfaces.
"""
import logging
from functools import partial

from autotrainer.behavior import PelletMachine, PelletState
from top_fixtures import property_value_save_transitions


def assert_load_cycle(pellet_m: PelletMachine, should_release: bool = True) -> None:
    """
    This is essentially the spec of what the behavior should be each time an ack is received from the real pellet device
    for a load->release cycle.  It defines what should happen in pellet_device_ack_received().  The state machine should
    pass tests using this, and then similarly pass when using an actual pellet device or mock.
    :param pellet_m: InferenceMachine instance
    :param should_release: True if pellet release is expected (vs. remaining covered)
    :return: None
    """
    pellet_m.load_pellet()

    assert pellet_m.state == PelletState.loading

    pellet_m.send_pellet()

    pellet_m._pellet_device_ack_received(pellet_m._api_status_token)

    assert pellet_m.state == PelletState.sending

    # When send completes, the machine transitions to covering in the ack that won't ever come in this testing.
    pellet_m.state = PelletState.covering

    pellet_m.release_pellet()

    pellet_m._pellet_device_ack_received(pellet_m._api_status_token)

    if should_release:

        assert pellet_m.state == PelletState.releasing

        pellet_m.monitor_pellet()

        assert pellet_m.state == PelletState.monitoring
    else:
        assert pellet_m.state == PelletState.covering


def assert_covered_was_released(machine: PelletMachine) -> None:
    """
    Verify that a covered pellet was release, which should also immediately transition to monitoring.
    :param machine: InferenceMachine instance
    :return: None
    """
    assert machine.state == PelletState.releasing

    machine.monitor_pellet()

    assert machine.state == PelletState.monitoring


def test_covered_load_cycle(mock_system, machine):
    pellet_m = machine.pellet
    # pellet_m = PelletMachine()

    assert_load_cycle(pellet_m, should_release=False)

    # Forcibly start a session for testing purposes.  This would normally occur at the system state level.
    pellet_m.algorithm.start_session()

    mock_system.make_recording_aged_enough()

    # Should transition to releasing if session starts while covered.
    assert_covered_was_released(pellet_m)

    assert pellet_m.state == PelletState.monitoring

    pellet_m.algorithm.end_session()

    pellet_m._pellet_device_ack_received(pellet_m._api_status_token)

    # Should return to covered at end of session
    assert pellet_m.state == PelletState.covering

    pellet_m.algorithm.start_session()

    mock_system.make_recording_aged_enough()

    pellet_m._pellet_device_ack_received(pellet_m._api_status_token)

    assert_covered_was_released(pellet_m)

    assert pellet_m.state == PelletState.monitoring

    pellet_m._pellet_device_ack_received(pellet_m._api_status_token)

    assert_load_cycle(pellet_m, should_release=True)

    pellet_m.algorithm.end_session()

    pellet_m._pellet_device_ack_received(pellet_m._api_status_token)

    assert pellet_m.state == PelletState.covering


def test_covered_disabled_load_cycle():
    machine = PelletMachine()

    state_transitions = []
    machine.events.state_changed += partial(property_value_save_transitions, transitions=state_transitions)

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
