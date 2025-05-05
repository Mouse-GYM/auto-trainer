import logging
import time
from datetime import datetime

from autotrainer.behavior import PelletState

from mocks import BehaviorMachineWithMocks

logging.basicConfig(level=logging.DEBUG)
logging.getLogger('transitions').setLevel(logging.INFO)


def test_enter_exit_default():
    machine = BehaviorMachineWithMocks()
    machine.algorithm.pellet_missing_time = 0.1

    pellet_machine = machine.pellet

    # Default state
    assert pellet_machine.state == PelletState.monitoring

    machine.enter_tunnel()

    assert pellet_machine.state == PelletState.releasing

    machine.mock_pellet.send_ack()

    assert pellet_machine.state == PelletState.monitoring

    machine.exit_tunnel()

    assert pellet_machine.state == PelletState.covering

    machine.mock_pellet.send_ack()

    machine.enter_tunnel()

    assert pellet_machine.state == PelletState.releasing

    machine.mock_pellet.send_ack()

    assert pellet_machine.state == PelletState.monitoring


def test_cover_pellet_enabled():
    """
    Should confirm that:
        A missing pellet triggers load in and out of tunnel
        Pellet is released if in tunnel, left covered if out of tunnel
        Pellet is covered if present when leaving tunnel and released if present when entering tunnel
    :return: None
    """
    machine = BehaviorMachineWithMocks()
    machine.algorithm.pellet_missing_time = 0.1

    pellet_machine = machine.pellet

    # Assumed default configuration.
    assert machine.algorithm.pellet_cover_enabled is True

    machine.enter_tunnel()

    assert pellet_machine.state == PelletState.releasing

    machine.mock_pellet.send_ack()

    assert pellet_machine.state == PelletState.monitoring

    # Send a pose response with pellet not seen which should trigger a load/release cycle while in tunnel.
    machine.mock_pellet_missing()

    machine.exit_tunnel()

    # Should have covered on exit.
    machine.expect_cover_command()

    machine.enter_tunnel()

    # Entering again should have triggered a release (uncover) of the covered pellet.
    machine.expect_pellet_delivery(was_covered=True)

    machine.exit_tunnel()

    # Already tested above, just confirm before next test.
    machine.expect_cover_command()

    # Send a pose response with pellet not seen which should trigger a load/cover cycle while out of tunnel.
    machine.mock_pose_response(False, False)

    assert pellet_machine.state == PelletState.loading

    machine.mock_pellet_missing(should_release=False, was_covered=False)

    # This should be the same as entering with it covered above.
    machine.enter_tunnel()

    # Entering again should have triggered a release (uncover) of the covered pellet.
    machine.expect_pellet_delivery(was_covered=True)


def test_cover_pellet_disabled():
    """
    Should confirm that:
        A missing pellet triggers load in and out of tunnel
        Pellet is released under all conditions
    :return: None
    """
    machine = BehaviorMachineWithMocks()
    machine.algorithm.pellet_missing_time = 0.1

    pellet_machine = machine.pellet

    # Turn off cover behavior
    machine.algorithm.pellet_cover_enabled = False

    machine.enter_tunnel()

    assert pellet_machine.state == PelletState.releasing

    machine.mock_pellet.send_ack()

    assert pellet_machine.state == PelletState.monitoring

    # Send a pose response with pellet not seen which should trigger a load/release cycle while in tunnel.
    machine.mock_pellet_missing(should_prerelease=True)

    machine.exit_tunnel()

    # Nothing should have changed.
    assert pellet_machine.state == PelletState.monitoring

    machine.enter_tunnel()

    # See comments in PelletMachine._session_starting.  Even though covering is disabled, this is expected.
    machine.expect_pellet_delivery(should_release=True, was_covered=True)

    machine.exit_tunnel()

    # Nothing should have changed.
    assert pellet_machine.state == PelletState.monitoring

    # Send a pose response with pellet not seen which should trigger a load/cover cycle while out of tunnel.
    machine.mock_pose_response(False, False)

    machine.mock_pellet_missing(should_release=True, should_prerelease=True)

    # This should be the same as entering with it covered above.
    machine.enter_tunnel()

    # See comment above.
    machine.expect_pellet_delivery(should_release=True, was_covered=True)


def test_pellet_seen():
    machine = BehaviorMachineWithMocks()
    machine.algorithm.pellet_missing_time = 0.25
    pellet_machine = machine.pellet
    algorithm = machine.algorithm

    machine.enter_tunnel()

    # Need to acknowledge the expected trigger to uncover
    machine.expect_pellet_delivery(was_covered=True)

    machine.mock_inference.mock_send_response(True, False)

    assert pellet_machine.state == PelletState.monitoring
    assert algorithm.pellet_last_seen != 0.0
    assert algorithm.session_pellet_count == 0

    # Again - nothing should happen
    machine.mock_inference.mock_send_response(True, False)

    assert pellet_machine.state == PelletState.monitoring
    assert algorithm.pellet_last_seen != 0.0
    assert algorithm.session_pellet_count == 0

    # Wait.  Nothing should again
    time.sleep(algorithm.limits.pellet_missing_time + 0.1)

    machine.mock_inference.mock_send_response(True, False)

    assert pellet_machine.state == PelletState.monitoring
    assert algorithm.pellet_last_seen != 0.0
    assert algorithm.session_pellet_count == 0

    # Miss a frame and then bring back
    machine.mock_inference.mock_send_response(False, False)

    assert pellet_machine.state == PelletState.monitoring
    assert algorithm.pellet_last_seen != 0.0
    assert algorithm.session_pellet_count == 0

    machine.mock_inference.mock_send_response(True, False)
    time.sleep(algorithm.limits.pellet_missing_time + 0.1)

    assert pellet_machine.state == PelletState.monitoring
    assert algorithm.pellet_last_seen != 0.0
    assert algorithm.session_pellet_count == 0


def test_session_limit():
    machine = BehaviorMachineWithMocks()
    machine.algorithm.pellet_missing_time = 0.1
    machine.algorithm.max_pellets_per_session = 2
    pellet_machine = machine.pellet
    algorithm = machine.algorithm

    assert algorithm.session_pellet_count == 0

    machine.enter_tunnel()

    # Need to acknowledge the expected trigger to uncover
    machine.expect_pellet_delivery(was_covered=True)

    machine.mock_pellet_missing()

    assert pellet_machine.state == PelletState.monitoring
    # assert algorithm.day_pellet_count == 1
    assert algorithm.session_pellet_count == 1

    machine.mock_pellet_missing()

    assert pellet_machine.state == PelletState.monitoring
    # assert algorithm.day_pellet_count == 2
    assert algorithm.session_pellet_count == 2

    # Session limit should have been reached

    machine.mock_pellet_missing(should_release=False)

    assert pellet_machine.state == PelletState.covering
    # assert algorithm.day_pellet_count == 2
    assert algorithm.session_pellet_count == 3

    # Start a new session
    machine.exit_tunnel()

    machine.enter_tunnel()

    # Need to acknowledge the expected trigger to uncover
    machine.expect_pellet_delivery(was_covered=True)

    # Previously covered re-released.
    assert pellet_machine.state == PelletState.monitoring
    # assert algorithm.day_pellet_count == 3
    assert algorithm.session_pellet_count == 0


# Disabled until day limit is implemented via reach detection.
def day_limit():
    machine = BehaviorMachineWithMocks()
    machine.algorithm.pellet_missing_time = 0.1
    machine.algorithm.max_pellets_per_day = 2

    pellet_machine = machine.pellet
    algorithm = machine.algorithm

    assert algorithm.day_pellet_count == 0

    machine.enter_tunnel()

    # Pellets one and two.
    machine.mock_pellet_missing()
    machine.mock_pellet_missing()

    assert pellet_machine.state == PelletState.monitoring
    assert algorithm.day_pellet_count == 2
    # Pellet over the day limit
    machine.mock_pellet_missing(should_release=False)

    assert pellet_machine.state == PelletState.covering
    assert algorithm.day_pellet_count == 2

    # Force the new day logic to trigger, if working correctly.  Should not access this field directly outside of
    # testing.
    algorithm._today = datetime(2000, 1, 1)

    # Trigger a release on a new day.  If a covered pellet is seen with the mouse in tunnel, it should release.
    machine.mock_pellet_seen(was_covered=True)

    assert pellet_machine.state == PelletState.monitoring
    assert algorithm.day_pellet_count == 1


if __name__ == '__main__':
    test_enter_exit_default()

    test_cover_pellet_enabled()

    test_cover_pellet_disabled()

    test_pellet_seen()

    test_session_limit()
