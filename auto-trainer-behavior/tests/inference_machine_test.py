import logging
import time
from datetime import datetime

from autotrainer.behavior import BehaviorAlgorithm, BehaviorLimits, InferenceState

from mocks import BehaviorMachineWithMocks

logging.basicConfig(level=logging.DEBUG)
logging.getLogger('transitions').setLevel(logging.INFO)


def test_enter_exit_tunnel():
    model = BehaviorMachineWithMocks(limits=BehaviorLimits(pellet_missing_time=0.1))
    inference_model = model.inference
    algorithm = model.algorithm

    # Default state
    assert inference_model.state == InferenceState.missing
    assert inference_model.is_in_tunnel is False
    assert algorithm.pellet_last_seen == 0.0
    assert algorithm.day_pellet_count == 0
    assert algorithm.session_pellet_count == 0
    assert algorithm.session_mouse_seen is False

    model.enter_tunnel()

    assert inference_model.state == InferenceState.missing
    assert inference_model.is_in_tunnel is True
    assert algorithm.pellet_last_seen == 0.0
    assert algorithm.day_pellet_count == 0
    assert algorithm.session_pellet_count == 0
    assert algorithm.session_mouse_seen is False

    model.exit_tunnel()

    assert inference_model.state == InferenceState.missing
    assert inference_model.is_in_tunnel is False
    assert algorithm.pellet_last_seen == 0.0
    assert algorithm.day_pellet_count == 0
    assert algorithm.session_pellet_count == 0
    assert algorithm.session_mouse_seen is False

    model.enter_tunnel()

    # Send a pose response with pellet part not seen which should trigger a load/release cycle.
    model.lose_pellet()

    assert inference_model.state == InferenceState.monitoring
    assert inference_model.is_in_tunnel is True
    assert algorithm.pellet_last_seen == 0.0
    assert algorithm.day_pellet_count == 1
    assert algorithm.session_pellet_count == 1
    assert algorithm.session_mouse_seen is False

    model.exit_tunnel()

    # Should cover pellet under normal circumstances.  Pellet counts should decrement.
    assert inference_model.state == InferenceState.covering
    assert inference_model.is_in_tunnel is False
    assert algorithm.pellet_last_seen == 0.0
    assert algorithm.day_pellet_count == 0
    assert algorithm.session_pellet_count == 0
    assert algorithm.session_mouse_seen is False

    model.enter_tunnel()

    model.pellet.send_ack()

    # Entering again should have triggered a release (uncover) of the covered pellet.
    model.expect_pellet_delivery(was_covered=True)

    # Should uncover pellet and increment pellet counts.
    assert inference_model.state == InferenceState.monitoring
    assert inference_model.is_in_tunnel is True
    assert algorithm.pellet_last_seen == 0.0
    assert algorithm.day_pellet_count == 1
    assert algorithm.session_pellet_count == 1
    assert algorithm.session_mouse_seen is False


def test_pellet_seen():
    model = BehaviorMachineWithMocks(limits=BehaviorLimits(pellet_missing_time=0.25))
    inference_model = model.inference
    algorithm = model.algorithm

    model.enter_tunnel()

    model.lose_pellet()

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

    model.enter_tunnel()

    model.lose_pellet()

    assert inference_model.state == InferenceState.monitoring
    assert algorithm.day_pellet_count == 1
    assert algorithm.session_pellet_count == 1

    model.lose_pellet()

    assert inference_model.state == InferenceState.monitoring
    assert algorithm.day_pellet_count == 2
    assert algorithm.session_pellet_count == 2

    # Session limit should have been reached

    model.lose_pellet(should_release=False)

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

    model.enter_tunnel()

    # Pellets one and two.
    model.lose_pellet()
    model.lose_pellet()

    assert inference_model.state == InferenceState.monitoring
    assert algorithm.day_pellet_count == 2
    # Pellet over the day limit
    model.lose_pellet(should_release=False)

    assert inference_model.state == InferenceState.covering
    assert algorithm.day_pellet_count == 2

    # Force the new day logic to trigger, if working correctly.  Should not access this field directly outside of
    # testing.
    algorithm._today = datetime(2000, 1, 1)

    # Trigger a release on a new day.  Pellet is in sending state based on previous step.
    model.lose_pellet(was_covered=True)

    assert inference_model.state == InferenceState.monitoring
    assert algorithm.day_pellet_count == 1


if __name__ == '__main__':
    test_enter_exit_tunnel()

    test_pellet_seen()

    test_session_limit()

    test_day_limit()
