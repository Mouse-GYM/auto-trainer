from functools import partial

import logging
from unittest import mock

import pytest

from autotrainer.behavior import SystemState, PelletState, SystemMachine, TunnelDeviceProtocol
from autotrainer.behavior.analysis.intersession_process import IntersessionResponse
from autotrainer.core import Notification, TriggerNotification, NotificationCenter, SensorAnalysis, \
    HeadbarPressureMonitor

from .mocks import BehaviorMachineWithMocks
from .conftest import on_state_changed


logging.basicConfig(level=logging.DEBUG)
logging.getLogger('transitions').setLevel(logging.INFO)


@pytest.fixture
def machine():
    return BehaviorMachineWithMocks()


def test_enter_exit_tunnel():
    # Observe for video capture being triggered.
    is_capture_triggered = False

    def set_capture_triggered(notification: Notification):
        nonlocal is_capture_triggered
        is_capture_triggered = notification.context

    NotificationCenter.default_center().add_observer(TriggerNotification.CAPTURE_ID, set_capture_triggered)

    machine = BehaviorMachineWithMocks()

    state_transitions = []
    machine.events.state_changed += partial(on_state_changed, state_transitions=state_transitions)

    # Current code assumes intersession analysis is off by default.
    assert machine.algorithm.intersession_enabled is False

    # Defaults
    assert machine.state == SystemState.cage
    assert machine.mock_headfix.current_position == 0
    assert machine.algorithm._is_in_session is False

    # Should trigger enter tunnel, new session, and associated changes.
    machine.mock_analysis.mock_load_cell_engaged(True)

    assert machine.state == SystemState.tunnel
    assert machine.mock_headfix.current_position == machine.algorithm.baseline_intensity
    assert machine.algorithm._is_in_session is True
    assert is_capture_triggered is True

    # Exit tunnel and end session.
    machine.mock_analysis.mock_load_cell_engaged(False)

    assert machine.state == SystemState.cage
    assert machine.algorithm._is_in_session is False
    assert is_capture_triggered is False
    assert state_transitions == [
        SystemState.tunnel,
        SystemState.cage,
    ]



def test_no_session_without_pellet():
    machine = BehaviorMachineWithMocks()

    state_transitions = []
    machine.events.state_changed += partial(on_state_changed, state_transitions=state_transitions)

    assert machine.algorithm.is_in_session is False

    # Lose the pellet (pellet state machine initializes to monitoring).  Pellet machine will be in loading state.
    machine.mock_pose_response(False, False)

    machine.mock_analysis.mock_load_cell_engaged(True)

    # Pellet machine not sending/releasing/monitoring - should not start.
    assert machine.algorithm.is_in_session is False

    machine.mock_analysis.mock_load_cell_engaged(False)

    # Cycle through pellet loading cycle so at next entrance a pellet is present.  In all of these cases recording/the
    # session should start because the send command happened out of tunnel and will not have triggered it.

    # Acknowledge load command -> should go to sending.
    machine.mock_pellet.send_ack()

    machine.mock_analysis.mock_load_cell_engaged(True)

    assert machine.algorithm.is_in_session is True

    machine.mock_analysis.mock_load_cell_engaged(False)

    # Acknowledge send command -> should go to releasing.
    machine.mock_pellet.send_ack()

    machine.mock_analysis.mock_load_cell_engaged(True)

    assert machine.algorithm.is_in_session is True

    machine.mock_analysis.mock_load_cell_engaged(False)

    # Acknowledge release command -> should go to monitoring.
    machine.mock_pellet.send_ack()

    machine.mock_analysis.mock_load_cell_engaged(True)

    assert machine.algorithm.is_in_session is True

    machine.mock_analysis.mock_load_cell_engaged(False)
    assert state_transitions == 4 * [
        SystemState.tunnel,
        SystemState.cage,
    ]


def test_intersession_enabled():
    """
    Placeholder for intersession analysis when ready.  Will not test details of intersession state machine, but that the
    system changes are as expected.
    :return: None
    """
    machine = BehaviorMachineWithMocks()

    state_transitions = []
    machine.events.state_changed += partial(on_state_changed, state_transitions=state_transitions)

    machine.algorithm.intersession_enabled = True

    machine.mock_analysis.mock_load_cell_engaged(True)

    machine.mock_inference.mock_send_response(False, True)

    machine.mock_analysis.mock_load_cell_engaged(False)

    assert machine.state == SystemState.intersession
    assert state_transitions == [
        SystemState.tunnel,
        SystemState.cage,
        SystemState.intersession,
    ]


def test_inference_detection_ready(machine):
    result = IntersessionResponse(
        food_consumed=20,
        pellet_x=50,
        pellets_presented=40,
        successful_reaches=4,
    )
    machine._inference.detection_result_ready(result)
    algo = machine.algorithm
    assert algo.session_pellet_count == 20
    assert algo.day_pellet_count == 20
    assert algo.successful_reaches == 4
    assert algo.pellets_presented == 40
    #
    result.food_consumed = 15
    result.successful_reaches = 2
    result.pellets_presented = 30
    machine._inference.detection_result_ready(result)
    assert algo.session_pellet_count == 35
    assert algo.day_pellet_count == 35
    assert algo.pellets_presented == 30
    assert algo.successful_reaches == 2


class TestAutoClamp:

    @pytest.fixture
    def machine(self):
        self._tunnel_dev = mock.create_autospec(TunnelDeviceProtocol)
        machine = SystemMachine(
            tunnel_device=self._tunnel_dev,
            analysis=SensorAnalysis(),
        )
        return machine

    @pytest.mark.parametrize("state", list(SystemState))
    @pytest.mark.parametrize("intensities", [[15, 20, 60], [100]])
    @pytest.mark.parametrize("hbp_engaged", [False, True])
    @pytest.mark.parametrize("head_fixation_enabled", [False, True])
    def test_with_analysis_pressure_prop_changed(self, machine, state, intensities, hbp_engaged, head_fixation_enabled):
        machine.state = state
        machine.algorithm.head_fixation_enabled = head_fixation_enabled
        analysis = machine._analysis
        for intensity in intensities:
            machine.algorithm.auto_clamp_intensity = intensity
            analysis.headbar_pressure_monitor.property_changed(
                HeadbarPressureMonitor.IS_ENGAGED_PROPERTY, hbp_engaged, None,
            )
        if state == SystemState.tunnel and hbp_engaged and head_fixation_enabled:
            assert self._tunnel_dev.update_head_magnet_intensity.call_args_list == [
                mock.call(i) for i in intensities
            ]
        else:
            assert self._tunnel_dev.update_head_magnet_intensity.call_args_list == []


if __name__ == '__main__':
    test_enter_exit_tunnel()
    test_intersession_enabled()
    test_no_session_without_pellet()
