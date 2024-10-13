import logging
import time
from datetime import datetime

from autotrainer.behavior import BehaviorAlgorithm, BehaviorLimits, InferenceBehaviorMachine, InferenceState

from mocks import BehaviorMachineWithMocks

logging.basicConfig(level=logging.DEBUG)
logging.getLogger('transitions').setLevel(logging.INFO)


def test_inference_behavior():
    """Tests transition behavior using input from pellet changes and commands"""
    properties = BehaviorAlgorithm(BehaviorLimits(max_pellets_per_session=2, max_pellets_per_day=3))

    model = BehaviorMachineWithMocks(properties)
    inference_model = model.inference

    assert inference_model.state == InferenceState.monitoring

    assert properties.pellet_last_seen == 0.0
    assert properties.day_pellet_count == 0
    assert properties.session_pellet_count == 0
    assert properties.session_mouse_seen is False

    model.pose.send_response(False, False)

    model.expect_pellet_delivery()

    assert properties.pellet_last_seen == 0.0
    assert properties.day_pellet_count == 1
    assert properties.session_pellet_count == 1
    assert properties.session_mouse_seen is False

    assert inference_model.state == InferenceState.monitoring

    model.pose.send_response(True, False)

    assert properties.pellet_last_seen != 0.0
    assert properties.day_pellet_count == 1
    assert properties.session_pellet_count == 1
    assert properties.session_mouse_seen is False

    # Ensure pellet load is triggered given the wait time
    time.sleep(properties.limits.pellet_missing_time + 0.5)

    model.pose.send_response(False, False)

    model.expect_pellet_delivery()

    assert properties.pellet_last_seen != 0.0
    assert properties.day_pellet_count == 2
    assert properties.session_pellet_count == 2
    assert properties.session_mouse_seen is False

    #  Met session pellet limit - pellet should load, but not release
    model.pose.send_response(False, True)

    model.expect_pellet_delivery(False)

    assert inference_model.state == InferenceState.sending
    assert properties.pellet_last_seen != 0.0
    assert properties.day_pellet_count == 2
    assert properties.session_pellet_count == 2
    assert properties.session_mouse_seen is True

    # Start a new session
    properties.start_session()
    assert properties.pellet_last_seen == 0.0
    assert properties.day_pellet_count == 2
    assert properties.session_pellet_count == 0
    assert properties.session_mouse_seen is False

    # First pellet of new session, 3rd pellet of day - should trigger a release from already loaded
    model.pose.send_response(False, False)

    model.expect_pellet_delivery(expected_release=False)

    assert properties.pellet_last_seen == 0.0
    assert properties.day_pellet_count == 3
    assert properties.session_pellet_count == 1
    assert properties.session_mouse_seen is False

    # 4rd pellet of day - should not trigger a response
    model.pose.send_response(False, False)

    model.expect_pellet_delivery(False)

    assert properties.pellet_last_seen == 0.0
    assert properties.day_pellet_count == 3
    assert properties.session_pellet_count == 1
    assert properties.session_mouse_seen is False

    # Force the new day logic, if working correctly, to trigger.  Should not access this field directly outside of
    # testing.
    properties._today = datetime(2000, 1, 1)

    # Trigger a release on a new day.  Pellet is in sending state based on previous step.
    time.sleep(properties.limits.pellet_missing_time + 0.01)
    model.pose.send_response(False, False)

    model.expect_pellet_delivery(expected_release=False)

    assert properties.pellet_last_seen == 0.0
    assert properties.day_pellet_count == 1
    # This assumes a new day does not interrupt or reset an ongoing session.
    assert properties.session_pellet_count == 2
    assert properties.session_mouse_seen is False

    # TODO test pellet_delivery_enabled property behaves as expected


if __name__ == '__main__':
    test_inference_behavior()
