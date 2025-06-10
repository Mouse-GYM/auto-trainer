from datetime import datetime

import pytest

from autotrainer.behavior import PelletState, SystemState


def test_enter_exit_default(mock_system, machine):

    machine.algorithm.pellet_missing_time = 0.1

    pellet_machine = machine.pellet

    # Default state
    assert pellet_machine.state == PelletState.monitoring

    machine.enter_tunnel()

    assert pellet_machine.state == PelletState.releasing

    mock_system.mock_pellet_ack()

    assert pellet_machine.state == PelletState.monitoring

    machine.exit_tunnel()

    assert pellet_machine.state == PelletState.covering

    mock_system.mock_pellet_ack()

    machine.enter_tunnel()

    assert pellet_machine.state == PelletState.releasing

    mock_system.mock_pellet_ack()

    assert pellet_machine.state == PelletState.monitoring
    assert mock_system.pellet_state_trans == [
        PelletState.releasing,
        PelletState.monitoring,
        PelletState.covering,
        PelletState.releasing,
        PelletState.monitoring
    ]
    assert machine.state == SystemState.tunnel
    assert mock_system.machine_state_trans == [SystemState.tunnel, SystemState.cage, SystemState.tunnel]


def test_cover_pellet_enabled(mock_system, machine):
    """
    Should confirm that:
        A missing pellet triggers load in and out of tunnel
        Pellet is released if in tunnel, left covered if out of tunnel
        Pellet is covered if present when leaving tunnel and released if present when entering tunnel
    :return: None
    """
    machine.algorithm.pellet_missing_time = 0.1

    pellet_machine = machine.pellet

    # Assumed default configuration.
    assert machine.algorithm.pellet_cover_enabled is True

    machine.enter_tunnel()

    assert pellet_machine.state == PelletState.releasing

    mock_system.mock_pellet_ack()

    assert pellet_machine.state == PelletState.monitoring

    # Send a pose response with pellet not seen which should trigger a load/release cycle while in tunnel.
    mock_system.mock_pellet_missing()

    machine.exit_tunnel()

    # Should have covered on exit.
    mock_system.expect_cover_command()

    machine.enter_tunnel()

    # Entering again should have triggered a release (uncover) of the covered pellet.
    mock_system.expect_pellet_delivery(was_covered=True)

    machine.exit_tunnel()

    # Already tested above, just confirm before next test.
    mock_system.expect_cover_command()

    # Send a pose response with pellet not seen which should trigger a load/cover cycle while out of tunnel.
    mock_system.mock_pose_response(False, False)

    assert pellet_machine.state == PelletState.loading

    mock_system.mock_pellet_missing(should_release=False, was_covered=False)

    # This should be the same as entering with it covered above.
    machine.enter_tunnel()

    # Entering again should have triggered a release (uncover) of the covered pellet.
    mock_system.expect_pellet_delivery(was_covered=True)

    assert machine.state == SystemState.tunnel

    assert mock_system.system_state_trans == mock_system.machine_state_trans
    assert mock_system.machine_state_trans == [
        SystemState.tunnel,
        SystemState.cage,
        SystemState.tunnel,
        SystemState.cage,
        SystemState.tunnel,
    ]
    assert mock_system.pellet_state_trans == [
        PelletState.releasing,

        PelletState.monitoring,

        PelletState.loading,
        PelletState.sending,
        PelletState.covering,
        PelletState.releasing,

        PelletState.monitoring,

        PelletState.covering,
        PelletState.releasing,

        PelletState.monitoring,

        PelletState.covering,
        PelletState.loading,
        PelletState.sending,
        PelletState.covering,
        PelletState.releasing,

        PelletState.monitoring,
    ]


def test_cover_pellet_disabled(mock_system, machine):
    """
    Should confirm that:
        A missing pellet triggers load in and out of tunnel
        Pellet is released under all conditions
    :return: None
    """
    machine.algorithm.pellet_missing_time = 0.1

    pellet_machine = machine.pellet

    # Turn off cover behavior
    machine.algorithm.pellet_cover_enabled = False

    machine.enter_tunnel()

    assert pellet_machine.state == PelletState.releasing

    mock_system.mock_pellet_ack()

    assert pellet_machine.state == PelletState.monitoring

    # Send a pose response with pellet not seen which should trigger a load/release cycle while in tunnel.
    mock_system.mock_pellet_missing(should_prerelease=True)

    machine.exit_tunnel()

    # Nothing should have changed.
    assert pellet_machine.state == PelletState.monitoring

    machine.enter_tunnel()

    # See comments in PelletMachine._session_starting.  Even though covering is disabled, this is expected.
    mock_system.expect_pellet_delivery(should_release=True, was_covered=True)

    machine.exit_tunnel()

    # Nothing should have changed.
    assert pellet_machine.state == PelletState.monitoring

    # Send a pose response with pellet not seen which should trigger a load/cover cycle while out of tunnel.
    mock_system.mock_pose_response(False, False)

    mock_system.mock_pellet_missing(should_release=True, should_prerelease=True)

    # This should be the same as entering with it covered above.
    machine.enter_tunnel()

    # See comment above.
    mock_system.expect_pellet_delivery(should_release=True, was_covered=True)


def test_pellet_seen(mock_system, machine, inference):
    machine.algorithm.pellet_missing_time = 0.25
    pellet_machine = machine.pellet
    algorithm = machine.algorithm
    machine.enter_tunnel()
    assert pellet_machine.state == PelletState.releasing

    # Need to acknowledge the expected trigger to uncover
    mock_system.expect_pellet_delivery(was_covered=True)

    mock_system.mock_pose_response(True, True)
    assert pellet_machine.state == PelletState.monitoring
    assert algorithm.pellet_last_seen != 0.0
    assert algorithm.session_pellet_count == 0

    mock_system.mock_pose_response(True, False)
    assert pellet_machine.state == PelletState.monitoring
    assert algorithm.pellet_last_seen != 0.0
    assert algorithm.session_pellet_count == 0

    # Miss a frame and then bring back
    mock_system.mock_pose_response(False, False)

    assert pellet_machine.state == PelletState.monitoring
    assert algorithm.pellet_last_seen != 0.0
    assert algorithm.session_pellet_count == 0

    mock_system.mock_pose_response(True, False)

    # time.sleep(algorithm.limits.pellet_missing_time + 0.1)

    assert machine.state == SystemState.tunnel
    assert pellet_machine.state == PelletState.monitoring
    assert algorithm.pellet_last_seen != 0.0
    assert algorithm.session_pellet_count == 0


def test_session_limit(mock_system, machine):
    machine.algorithm.pellet_missing_time = 0.1
    machine.algorithm.max_pellets_per_session = 2
    pellet_machine = machine.pellet
    algorithm = machine.algorithm

    assert algorithm.session_pellet_count == 0

    machine.enter_tunnel()

    # Need to acknowledge the expected trigger to uncover
    mock_system.expect_pellet_delivery(was_covered=True)

    mock_system.mock_pellet_missing()

    assert pellet_machine.state == PelletState.monitoring
    # assert algorithm.day_pellet_count == 1
    assert algorithm.session_pellet_count == 1

    mock_system.mock_pellet_missing()

    assert pellet_machine.state == PelletState.monitoring
    # assert algorithm.day_pellet_count == 2
    assert algorithm.session_pellet_count == 2

    # Session limit should have been reached

    mock_system.mock_pellet_missing(should_release=False)

    assert pellet_machine.state == PelletState.covering
    # assert algorithm.day_pellet_count == 2
    assert algorithm.session_pellet_count == 3

    # Start a new session
    machine.exit_tunnel()

    machine.enter_tunnel()

    # Need to acknowledge the expected trigger to uncover
    mock_system.expect_pellet_delivery(was_covered=True)

    # Previously covered re-released.
    assert pellet_machine.state == PelletState.monitoring
    # assert algorithm.day_pellet_count == 3
    assert algorithm.session_pellet_count == 0

    assert mock_system.machine_state_trans == mock_system.system_state_trans
    assert mock_system.machine_state_trans == [
        SystemState.tunnel,
        SystemState.cage,
        SystemState.tunnel,
    ]
    assert mock_system.pellet_state_trans == [
        PelletState.releasing,

        PelletState.monitoring,

        PelletState.loading,
        PelletState.sending,
        PelletState.covering,
        PelletState.releasing,

        PelletState.monitoring,

        PelletState.loading,
        PelletState.sending,
        PelletState.covering,
        PelletState.releasing,

        PelletState.monitoring,

        PelletState.loading,
        PelletState.sending,
        PelletState.covering,
        PelletState.releasing,

        PelletState.monitoring,
    ]


@pytest.mark.xfail(reason="Disabled until day limit is implemented via reach detection.")
def test_day_limit(machine, mock_system):
    machine.algorithm.pellet_missing_time = 0.1
    machine.algorithm.max_pellets_per_day = 2

    pellet_machine = machine.pellet
    algorithm = machine.algorithm

    assert algorithm.day_pellet_count == 0

    machine.enter_tunnel()

    # Pellets one and two.
    mock_system.mock_pellet_missing()
    mock_system.mock_pellet_missing()

    assert pellet_machine.state == PelletState.monitoring
    assert algorithm.day_pellet_count == 2
    # Pellet over the day limit
    mock_system.mock_pellet_missing(should_release=False)

    assert pellet_machine.state == PelletState.covering
    assert algorithm.day_pellet_count == 2

    # Force the new day logic to trigger, if working correctly.  Should not access this field directly outside of
    # testing.
    algorithm._today = datetime(2000, 1, 1)

    # Trigger a release on a new day.  If a covered pellet is seen with the mouse in tunnel, it should release.
    mock_system.mock_pellet_seen(was_covered=True)

    assert pellet_machine.state == PelletState.monitoring
    assert algorithm.day_pellet_count == 1
