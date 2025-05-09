
import logging
from functools import partial
from threading import Timer
from unittest import mock

import pytest
import time

from autotrainer.behavior import TunnelDeviceProtocol, PelletDeviceProtocol
from autotrainer.core import SensorAnalysis, HeadbarPressureMonitor

from autotrainer.behavior import SystemState, PelletState, SystemMachine
from autotrainer.behavior.analysis.intersession_process import IntersessionResponse
from autotrainer.core import Notification, TriggerNotification, NotificationCenter

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
            pellet_device=mock.create_autospec(PelletDeviceProtocol),
            analysis=SensorAnalysis(),
        )
        return machine

    @pytest.mark.parametrize("state", list(SystemState))
    @pytest.mark.parametrize("intensities", [[15, 20, 60], [100], ["base"]])
    @pytest.mark.parametrize("hbp_engaged", [True, False])
    @pytest.mark.parametrize("head_fixation_enabled", [True, False])
    def test_with_analysis_pressure_prop_changed(self, machine, state, intensities, hbp_engaged, head_fixation_enabled):
        machine.state = state
        machine.algorithm.start_session()
        machine.algorithm.head_fixation_enabled = head_fixation_enabled
        analysis = machine._analysis
        tun_dev = self._tunnel_dev
        for idx, intensity in enumerate(intensities):
            if intensity == "base":
                intensity = machine.algorithm.baseline_intensity
                intensities[idx] = intensity
            machine.algorithm.auto_clamp_intensity = intensity
            analysis.headbar_pressure_monitor.property_changed(
                HeadbarPressureMonitor.IS_ENGAGED_PROPERTY, hbp_engaged, None,
            )
        if state == SystemState.tunnel and hbp_engaged and head_fixation_enabled:
            assert tun_dev.update_head_magnet_intensity.call_args_list == [
                mock.call(i) for i in intensities
            ]
        else:
            assert tun_dev.update_head_magnet_intensity.call_args_list == []
        #
        tun_dev.reset_mock()
        def patch_timer(delay, func):
            m = mock.create_autospec(Timer)
            m.start.side_effect = func
            return m
        with mock.patch("autotrainer.behavior.system_machine.Timer", autospec=True) as m_timer:
            m_timer.side_effect = patch_timer
            machine.algorithm.head_fixation_enabled = False  # Disable auto-clamp
        # This above mock patch allow to not have to :
        #   time.sleep(machine.algorithm.auto_clamp_release_delay + 0.0005)
        # and/but not be always sure that the timer has completed...
        # NB:
        # This is eventually fragile if other Timer (than the exact one desired (in the same module that is)) were
        #  created during the same code execution.

        # Now ensure update_head_magnet_intensity has been called as desired (or not):
        if head_fixation_enabled:  # if auto-clamp was engaged
            exp_update_head_magnet = [mock.call(machine.algorithm.baseline_intensity)]
            exp_play_tone = [
                mock.call(machine.algorithm.auto_clamp_release_tone_freq, 0.5)
            ]
        else:
            exp_update_head_magnet = exp_play_tone = []
        #
        assert tun_dev.update_head_magnet_intensity.call_args_list == exp_update_head_magnet
        assert machine._pellet_device.play_tone.call_args_list == exp_play_tone

    @pytest.mark.parametrize("start_session", [False, True])
    def test_auto_clamp_session_off_reset_to_baseline(self, machine, start_session):
        machine.state = SystemState.tunnel
        if start_session:
            machine.algorithm.start_session()
        tun_dev = self._tunnel_dev
        assert tun_dev.update_head_magnet_intensity.call_args_list == []
        #
        # used with debugger:
        # def catch(*args, **kwargs):
        #     pass
        # tun_dev.update_head_magnet_intensity.side_effect = catch
        machine.after_exit_tunnel()

        nb = 2 if start_session else 1
        assert tun_dev.update_head_magnet_intensity.call_args_list == nb * [
            mock.call(machine.algorithm.baseline_intensity)
        ]  # it's called twice when in session:
        # once in after_exit_tunnel directly,
        # and once in _session_ended, as event handler from end_session -> session_ending
        assert machine._pellet_device.play_tone.call_args_list == []


if __name__ == '__main__':
    test_enter_exit_tunnel()
    test_intersession_enabled()
    test_no_session_without_pellet()
