import logging

from autotrainer.behavior import SystemState, PelletState
from autotrainer.core import TriggerManager, CAPTURE_TRIGGER_ID

from mocks import BehaviorMachineWithMocks

logging.basicConfig(level=logging.DEBUG)
logging.getLogger('transitions').setLevel(logging.INFO)


def test_enter_exit_tunnel():
    # Observe for video capture being triggered.
    is_capture_triggered = False

    def set_capture_triggered(_sender, _id, b: bool):
        nonlocal is_capture_triggered
        is_capture_triggered = b

    TriggerManager.instance().register(set_capture_triggered, CAPTURE_TRIGGER_ID)

    machine = BehaviorMachineWithMocks()

    # Current code assumes intersession analysis is off by default.
    assert machine.algorithm.intersession_enabled is False

    # Defaults
    assert machine.state == SystemState.cage
    assert machine.mock_headfix.current_position == 0
    assert machine.algorithm._is_in_session is False

    # Should trigger enter tunnel, new session, and associated changes.
    machine.mock_headfix.mock_load_cell_engaged(True)

    assert machine.state == SystemState.tunnel
    assert machine.mock_headfix.current_position == machine.algorithm.baseline_intensity
    assert machine.algorithm._is_in_session is True
    assert is_capture_triggered is True

    # Exit tunnel and end session.
    machine.mock_headfix.mock_load_cell_engaged(False)

    assert machine.state == SystemState.cage
    assert machine.algorithm._is_in_session is False
    assert is_capture_triggered is False


def test_no_session_without_pellet():
    machine = BehaviorMachineWithMocks()

    assert machine.algorithm.is_in_session is False

    # Lose the pellet (pellet state machine initializes to monitoring).  Pellet machine will be in loading state.
    machine.mock_pose_response(False, False)

    machine.mock_headfix.mock_load_cell_engaged(True)

    # Pellet machine not sending/releasing/monitoring - should not start.
    assert machine.algorithm.is_in_session is False

    machine.mock_headfix.mock_load_cell_engaged(False)

    # Cycle through pellet loading cycle so at next entrance a pellet is present.  In all of these cases recording/the
    # session should start because the send command happened out of tunnel and will not have triggered it.

    # Acknowledge load command -> should go to sending.
    machine.mock_pellet.send_ack()

    machine.mock_headfix.mock_load_cell_engaged(True)

    assert machine.algorithm.is_in_session is True

    machine.mock_headfix.mock_load_cell_engaged(False)

    # Acknowledge send command -> should go to releasing.
    machine.mock_pellet.send_ack()

    machine.mock_headfix.mock_load_cell_engaged(True)

    assert machine.algorithm.is_in_session is True

    machine.mock_headfix.mock_load_cell_engaged(False)

    # Acknowledge release command -> should go to monitoring.
    machine.mock_pellet.send_ack()

    machine.mock_headfix.mock_load_cell_engaged(True)

    assert machine.algorithm.is_in_session is True

    machine.mock_headfix.mock_load_cell_engaged(False)


def test_intersession_enabled():
    """
    Placeholder for intersession analysis when ready.  Will not test details of intersession state machine, but that the
    system changes are as expected.
    :return: None
    """
    machine = BehaviorMachineWithMocks()

    machine.algorithm.intersession_enabled = True

    machine.mock_headfix.mock_load_cell_engaged(True)

    machine.mock_inference.mock_send_response(False, True)

    machine.mock_headfix.mock_load_cell_engaged(False)

    assert machine.state == SystemState.intersession


if __name__ == '__main__':
    test_enter_exit_tunnel()

    test_intersession_enabled()

    test_no_session_without_pellet()
