import logging
import time
from datetime import datetime

from autotrainer.behavior import BehaviorLimits, InferenceState

from mocks import BehaviorMachineWithMocks

logging.basicConfig(level=logging.DEBUG)
logging.getLogger('transitions').setLevel(logging.INFO)


def test_enter_exit_default():
    machine = BehaviorMachineWithMocks(limits=BehaviorLimits(pellet_missing_time=0.1))

    inference_machine = machine.inference

    # Default state
    assert inference_machine.state == InferenceState.missing

    machine.enter_tunnel()

    assert inference_machine.state == InferenceState.missing

    machine.exit_tunnel()

    assert inference_machine.state == InferenceState.missing

    machine.enter_tunnel()

    assert inference_machine.state == InferenceState.missing


def test_cover_pellet_enabled():
    """
    Should confirm that:
        A missing pellet triggers load in and out of tunnel
        Pellet is released if in tunnel, left covered if out of tunnel
        Pellet is covered if present when leaving tunnel and released if present when entering tunnel
    :return: None
    """
    machine = BehaviorMachineWithMocks(limits=BehaviorLimits(pellet_missing_time=0.1))

    inference_machine = machine.inference

    # Assumed default configuration.
    assert machine.algorithm.pellet_cover_enabled is True

    machine.enter_tunnel()

    assert inference_machine.state == InferenceState.missing

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

    assert inference_machine.state == InferenceState.missing

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
    machine = BehaviorMachineWithMocks(limits=BehaviorLimits(pellet_missing_time=0.1))

    inference_machine = machine.inference

    # Turn off cover behavior
    machine.algorithm.pellet_cover_enabled = False

    machine.enter_tunnel()

    assert inference_machine.state == InferenceState.missing

    # Send a pose response with pellet not seen which should trigger a load/release cycle while in tunnel.
    machine.mock_pellet_missing()

    machine.exit_tunnel()

    # Nothing should have changed.
    assert inference_machine.state == InferenceState.monitoring

    machine.enter_tunnel()

    # See comments in InferenceMachine._session_starting.  Even though covering is disabled, this is expected.
    machine.expect_pellet_delivery(should_release=True, was_covered=True)

    machine.exit_tunnel()

    # Nothing should have changed.
    assert inference_machine.state == InferenceState.monitoring

    # Send a pose response with pellet not seen which should trigger a load/cover cycle while out of tunnel.
    machine.mock_pose_response(False, False)

    machine.mock_pellet_missing(should_release=True)

    # This should be the same as entering with it covered above.
    machine.enter_tunnel()

    # See comment above.
    machine.expect_pellet_delivery(should_release=True, was_covered=True)

def test_pellet_seen():
    model = BehaviorMachineWithMocks(limits=BehaviorLimits(pellet_missing_time=0.25))
    inference_model = model.inference
    algorithm = model.algorithm

    model.enter_tunnel()

    model.mock_pellet_missing()

    model.pose.send_response(True, False)

    assert inference_model.state == InferenceState.monitoring
    assert algorithm.pellet_last_seen != 0.0
    assert algorithm.session_pellet_count == 1

    # Again - nothing should happen
    model.pose.send_response(True, False)

    assert inference_model.state == InferenceState.monitoring
    assert algorithm.pellet_last_seen != 0.0
    assert algorithm.session_pellet_count == 1

    # Wait.  Nothing should again
    time.sleep(algorithm.limits.pellet_missing_time + 0.1)

    model.pose.send_response(True, False)

    assert inference_model.state == InferenceState.monitoring
    assert algorithm.pellet_last_seen != 0.0
    assert algorithm.session_pellet_count == 1

    # Miss a frame and then bring back
    model.pose.send_response(False, False)

    assert inference_model.state == InferenceState.missing
    assert algorithm.pellet_last_seen != 0.0
    assert algorithm.session_pellet_count == 1

    model.pose.send_response(True, False)
    time.sleep(algorithm.limits.pellet_missing_time + 0.1)

    assert inference_model.state == InferenceState.monitoring
    assert algorithm.pellet_last_seen != 0.0
    assert algorithm.session_pellet_count == 1


def test_session_limit():
    model = BehaviorMachineWithMocks(limits=BehaviorLimits(pellet_missing_time=0.1, max_pellets_per_session=2))
    inference_model = model.inference
    algorithm = model.algorithm

    assert algorithm.session_pellet_count == 0

    model.enter_tunnel()

    model.mock_pellet_missing()

    assert inference_model.state == InferenceState.monitoring
    assert algorithm.day_pellet_count == 1
    assert algorithm.session_pellet_count == 1

    model.mock_pellet_missing()

    assert inference_model.state == InferenceState.monitoring
    assert algorithm.day_pellet_count == 2
    assert algorithm.session_pellet_count == 2

    # Session limit should have been reached

    model.mock_pellet_missing(should_release=False)

    assert inference_model.state == InferenceState.covering
    assert algorithm.day_pellet_count == 2
    assert algorithm.session_pellet_count == 2

    # Start a new session
    model.exit_tunnel()

    model.enter_tunnel()

    # Need to acknowledge the expected trigger to uncover
    model.expect_pellet_delivery(was_covered=True)

    # Previously covered re-released.
    assert inference_model.state == InferenceState.monitoring
    assert algorithm.day_pellet_count == 3
    assert algorithm.session_pellet_count == 1


def test_day_limit():
    model = BehaviorMachineWithMocks(limits=BehaviorLimits(pellet_missing_time=0.1, max_pellets_per_day=2))
    inference_model = model.inference
    algorithm = model.algorithm

    assert algorithm.day_pellet_count == 0

    model.enter_tunnel()

    # Pellets one and two.
    model.mock_pellet_missing()
    model.mock_pellet_missing()

    assert inference_model.state == InferenceState.monitoring
    assert algorithm.day_pellet_count == 2
    # Pellet over the day limit
    model.mock_pellet_missing(should_release=False)

    assert inference_model.state == InferenceState.covering
    assert algorithm.day_pellet_count == 2

    # Force the new day logic to trigger, if working correctly.  Should not access this field directly outside of
    # testing.
    algorithm._today = datetime(2000, 1, 1)

    # Trigger a release on a new day.  If a covered pellet is seen with the mouse in tunnel, it should release.
    model.mock_pellet_seen(was_covered=True)

    assert inference_model.state == InferenceState.monitoring
    assert algorithm.day_pellet_count == 1


if __name__ == '__main__':
    test_enter_exit_default()

    test_cover_pellet_enabled()

    test_cover_pellet_disabled()

    test_pellet_seen()

    test_session_limit()

    test_day_limit()
