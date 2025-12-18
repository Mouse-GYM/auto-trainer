import logging
from datetime import datetime
from unittest import mock

import pytest

from autotrainer.behavior import PelletState, SystemState, PelletMachine, PelletDeviceProtocol, BehaviorAlgorithm

from top_fixtures import MockSystemMachine


@pytest.fixture()
def pellet_machine():
    m_pellet_device = mock.create_autospec(PelletDeviceProtocol)
    BehaviorAlgorithm._no_handler_thread = True
    pellet_machine = PelletMachine(pellet_device=m_pellet_device)
    return pellet_machine


def test_enter_exit_default(mock_system, machine):

    algo = machine.algorithm
    algo.pellet_missing_time = 0.1

    pellet_m = machine.pellet

    # Default state
    assert not algo.is_in_session
    assert pellet_m.state == PelletState.monitoring

    assert machine.state == SystemState.cage

    machine._analysis.load_cell_monitor.is_engaged = True
    # machine.enter_tunnel()
    assert machine.state == SystemState.tunnel

    mock_system.make_recording_aged_enough()
    assert machine.algorithm.is_in_session

    assert pellet_m.state == PelletState.releasing

    mock_system.mock_pellet_ack()

    assert pellet_m.state == PelletState.monitoring

    machine._analysis.load_cell_monitor._is_engaged = False
    machine.exit_tunnel()

    assert pellet_m.state == PelletState.covering

    mock_system.mock_pellet_ack()

    machine.enter_tunnel()

    mock_system.make_recording_aged_enough()

    assert pellet_m.state == PelletState.releasing

    mock_system.mock_pellet_ack()

    assert pellet_m.state == PelletState.monitoring
    assert mock_system.pellet_state_trans == [
        PelletState.releasing,
        PelletState.monitoring,
        PelletState.covering,
        PelletState.releasing,
        PelletState.monitoring
    ]
    assert machine.state == SystemState.tunnel
    assert mock_system.machine_state_trans == [SystemState.tunnel, SystemState.cage, SystemState.tunnel]


def test_cover_pellet_enabled(mock_system: MockSystemMachine, machine):
    """
    Should confirm that:
        A missing pellet triggers load in and out of tunnel
        Pellet is released if in tunnel, left covered if out of tunnel
        Pellet is covered if present when leaving tunnel and released if present when entering tunnel
    :return: None
    """
    machine.algorithm.pellet_missing_time = 0.001

    pellet_m = machine.pellet

    # Assumed default configuration.
    assert machine.algorithm.pellet_cover_enabled is True
    assert pellet_m.state == PelletState.monitoring

    assert machine.state == SystemState.cage
    machine._analysis.load_cell_monitor.is_engaged = True
    assert machine.state == SystemState.tunnel
    # machine.enter_tunnel()

    assert pellet_m.state == PelletState.monitoring

    mock_system.make_recording_aged_enough()

    assert pellet_m.state == PelletState.releasing

    mock_system.mock_pellet_ack()

    assert pellet_m.state == PelletState.monitoring

    assert machine.state == SystemState.tunnel

    # mock_system.mock_pellet_ack()
    # Send a pose response with pellet not seen which should trigger a load/release cycle while in tunnel.
    try:
        mock_system.mock_pellet_missing()
    except AssertionError as err:
        logging.exception("Failed: %s", err)
        raise

    machine.exit_tunnel()
    assert machine.state == SystemState.cage

    # Should have covered on exit.
    mock_system.expect_cover_command()

    machine.enter_tunnel()

    assert machine.state == SystemState.tunnel
    assert pellet_m.state == PelletState.covering

    mock_system.make_recording_aged_enough()

    assert pellet_m.state == PelletState.releasing

    # Entering again should have triggered a release (uncover) of the covered pellet.
    mock_system.expect_pellet_delivery(was_covered=True)

    machine.exit_tunnel()

    assert machine.state == SystemState.cage
    assert pellet_m.state == PelletState.covering

    # Already tested above, just confirm before next test.
    mock_system.expect_cover_command()

    assert pellet_m.state == PelletState.covering

    # Send a pose response with pellet not seen which should trigger a load/cover cycle while out of tunnel.
    mock_system.mock_pose_response(False, False)

    assert pellet_m.state == PelletState.loading

    mock_system.mock_pellet_missing(should_release=False, was_covered=False)

    # This should be the same as entering with it covered above.
    machine.enter_tunnel()

    mock_system.make_recording_aged_enough()

    # Entering again should have triggered a release (uncover) of the covered pellet.
    mock_system.expect_pellet_delivery(was_covered=True)

    assert machine.state == SystemState.tunnel

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

    pellet = machine.pellet

    # Turn off cover behavior
    machine.algorithm.pellet_cover_enabled = False

    assert machine.state == SystemState.cage

    machine._analysis.load_cell_monitor.is_engaged = True
    # machine.enter_tunnel()
    assert machine.state == SystemState.tunnel

    mock_system.make_recording_aged_enough()

    assert pellet.state == PelletState.releasing

    mock_system.mock_pellet_ack()

    assert pellet.state == PelletState.monitoring

    # Send a pose response with pellet not seen which should trigger a load/release cycle while in tunnel.
    mock_system.mock_pellet_missing(should_prerelease=True)

    machine._analysis.load_cell_monitor._is_engaged = False
    machine.exit_tunnel()

    assert machine.state == SystemState.cage

    # Nothing should have changed.
    assert pellet.state == PelletState.monitoring

    machine._analysis.load_cell_monitor._is_engaged = True
    machine.enter_tunnel()

    assert machine.state == SystemState.tunnel
    mock_system.make_recording_aged_enough()

    # See comments in PelletMachine._session_starting.  Even though covering is disabled, this is expected.
    mock_system.expect_pellet_delivery(should_release=True, was_covered=True)

    machine._analysis.load_cell_monitor._is_engaged = False
    machine.exit_tunnel()

    assert machine.state == SystemState.cage

    # Nothing should have changed.
    assert pellet.state == PelletState.monitoring

    # Send a pose response with pellet not seen which should trigger a load/cover cycle while out of tunnel.
    mock_system.mock_pose_response(False, False)

    mock_system.mock_pellet_missing(should_release=True, should_prerelease=True)

    # This should be the same as entering with it covered above.
    machine._analysis.load_cell_monitor._is_engaged = True
    machine.enter_tunnel()

    mock_system.make_recording_aged_enough()

    # See comment above.
    mock_system.expect_pellet_delivery(should_release=True, was_covered=True)


def test_pellet_seen(mock_system, machine, inference):
    machine.algorithm.pellet_missing_time = 0.25
    pellet_dev = machine.pellet
    algorithm = machine.algorithm
    assert not algorithm.is_in_session
    machine._analysis.load_cell_monitor.is_engaged = True
    machine.enter_tunnel()
    assert algorithm.is_in_session
    mock_system.make_recording_aged_enough()

    assert pellet_dev.state == PelletState.releasing

    # Need to acknowledge the expected trigger to uncover
    mock_system.expect_pellet_delivery(was_covered=True)

    # looking at the following assertions, it appears we are not having/testing any variation..
    # maybe need to enh this test case..

    mock_system.mock_pose_response(True, True)
    assert pellet_dev.state == PelletState.monitoring
    assert algorithm.pellet_last_seen != 0.0
    assert algorithm.session_pellet_count == 0

    mock_system.mock_pose_response(True, False)
    assert pellet_dev.state == PelletState.monitoring

    assert algorithm.pellet_last_seen != 0.0
    assert algorithm.session_pellet_count == 0

    # Miss a frame and then bring back
    mock_system.mock_pose_response(False, False)

    assert pellet_dev.state == PelletState.monitoring
    assert algorithm.pellet_last_seen != 0.0
    assert algorithm.session_pellet_count == 0

    mock_system.mock_pose_response(True, False)

    assert machine.state == SystemState.tunnel
    assert pellet_dev.state == PelletState.monitoring
    assert algorithm.pellet_last_seen != 0.0
    assert algorithm.session_pellet_count == 0


def test_session_limit(mock_system, machine):
    # TODO: Session limits and associated logic currently on hold.
    return

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


@pytest.mark.parametrize("pellet_seen", [True, False])
@pytest.mark.parametrize("must_release", [True, False])
@pytest.mark.parametrize("pellet_state",
                         set(PelletState)
                         - {
                             PelletState.monitoring,
                             PelletState.home,
                             PelletState.loading,
                             PelletState.prerelease,
                         })
def test_move_home_when_intersession(pellet_machine, pellet_state, pellet_seen, must_release):
    pellet_machine.state = pellet_state
    pellet_machine.algorithm.system_state = SystemState.intersession
    pellet_machine.environment_changed(pellet_seen=pellet_seen, must_release=must_release)
    assert pellet_machine.state is PelletState.retract


@pytest.mark.parametrize("pellet_seen", [True, False])
@pytest.mark.parametrize("must_release", [True, False])
@pytest.mark.parametrize("system_state", sorted(set(SystemState) - {SystemState.intersession}))
def test_send_pellet_when_home(pellet_machine, system_state, pellet_seen, must_release):
    pellet_machine.state = PelletState.home
    pellet_machine.algorithm.system_state = system_state
    pellet_machine.environment_changed(pellet_seen=pellet_seen, must_release=must_release)
    assert pellet_machine.state is PelletState.sending


@pytest.mark.xfail(reason="Disabled until day limit is implemented via reach detection.")
def test_day_limit(machine, mock_system, pellet_machine):
    machine.algorithm.pellet_missing_time = 0.1
    machine.algorithm.max_pellets_per_day = 2

    # pellet_machine = machine.pellet
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
