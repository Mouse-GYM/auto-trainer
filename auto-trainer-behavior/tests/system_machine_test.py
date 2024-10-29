import logging

from autotrainer.behavior import SystemState
from autotrainer.core import TriggerManager, CAPTURE_TRIGGER_ID

from mocks import BehaviorMachineWithMocks

logging.basicConfig(level=logging.DEBUG)
logging.getLogger('transitions').setLevel(logging.INFO)


def test_enter_exit_tunnel():
    # Observe for capture being triggered.
    is_capture_triggered = False

    def set_capture_triggered(_sender, _id, b: bool):
        nonlocal is_capture_triggered
        is_capture_triggered = b

    TriggerManager.instance().register(set_capture_triggered, CAPTURE_TRIGGER_ID)

    model = BehaviorMachineWithMocks()

    assert model.state == SystemState.cage
    assert model.headfix.current_position == 0
    assert model.algorithm._is_in_session is False

    model.headfix.is_load_cell_engaged = True

    assert model.state == SystemState.tunnel
    assert model.headfix.current_position == model.algorithm.baseline_intensity
    assert model.algorithm._is_in_session is True
    assert is_capture_triggered is True

    model.headfix.is_load_cell_engaged = False

    assert model.state == SystemState.cage
    assert model.headfix.current_position == 0
    assert model.algorithm._is_in_session is False
    assert is_capture_triggered is False

    """
    model.headfix.is_load_cell_engaged = True

    model.pose.send_response(False, True)

    model.headfix.is_load_cell_engaged = False

    assert model.state == SystemState.intersession
    """


if __name__ == '__main__':
    test_enter_exit_tunnel()
