import contextlib
import logging
import math
import time
from itertools import chain
from pathlib import Path
from threading import Timer
from unittest import mock

import pytest

from top_fixtures import MockSystemMachine


from autotrainer.core import HeadbarPressureMonitor
from autotrainer.core import Notification, TriggerNotification, NotificationCenter

from autotrainer.behavior import PelletMachine, CaptureAnalysisResult
from autotrainer.behavior import SystemState, PelletState, SystemMachine

from autotrainer.inference.analysis.intersession_process import IntersessionResponse


def test_enter_exit_tunnel(mock_system, machine):
    # Observe for video capture being triggered.
    is_capture_triggered = False

    def set_capture_triggered(notification: Notification):
        nonlocal is_capture_triggered
        is_capture_triggered = notification.context

    NotificationCenter.default_center().add_observer(TriggerNotification.CAPTURE_ID, set_capture_triggered)

    tun_dev = machine._tunnel_device

    # Current code assumes intersession analysis is off by default.
    assert machine.algorithm.intersession_enabled is False

    # Defaults
    assert machine.state == SystemState.cage
    # assert machine.mock_headfix.current_position == 0
    assert tun_dev.update_head_magnet_intensity.call_args_list == []
    assert machine.algorithm.is_in_session is False

    # Should trigger enter tunnel, new session, and associated changes.
    mock_system.make_load_cell_active()

    assert machine.state == SystemState.tunnel
    assert tun_dev.update_head_magnet_intensity.call_args_list == [
        mock.call(machine.algorithm.baseline_intensity)
    ]
    assert machine.algorithm.is_in_session is True
    assert is_capture_triggered is True

    # Exit tunnel and end session.
    # machine.mock_analysis.mock_load_cell_engaged(False)
    mock_system.make_load_cell_inactive()

    assert machine.state == SystemState.cage
    assert machine.algorithm.is_in_session is False
    assert is_capture_triggered is False
    assert mock_system.machine_state_trans == [
        SystemState.tunnel,
        SystemState.cage,
    ]


def test_no_session_without_pellet(mock_system, machine: SystemMachine):
    pellet_machine = machine._pellet_machine
    assert isinstance(pellet_machine, PelletMachine)

    def pellet_ack_received():
        pellet_machine._pellet_device_ack_received(pellet_machine._api_status_token)

    assert machine.algorithm.is_in_session is False

    # Lose the pellet (pellet state machine initializes to monitoring).  Pellet machine will be in loading state.
    mock_system.mock_pose_response(False, False)

    assert mock_system.pellet_state_trans == [PelletState.loading]
    mock_system.pellet_state_trans.clear()

    assert mock_system.machine_state_trans == []

    mock_system.make_load_cell_active()

    mock_system.make_recording_aged_enough()

    assert mock_system.pellet_state_trans == []
    assert mock_system.machine_state_trans == [SystemState.tunnel]
    # Pellet machine not sending/releasing/monitoring - should not start.

    # assert machine.algorithm.is_in_session is False
    # NO: we now always start a session recording any time load cell is engaged, whatever is pellet status

    mock_system.make_load_cell_inactive()

    assert machine.algorithm.is_in_session is False
    assert mock_system.machine_state_trans == [SystemState.tunnel, SystemState.cage]

    # Cycle through pellet loading cycle so at next entrance a pellet is present.  In all of these cases recording/the
    # session should start because the send command happened out of tunnel and will not have triggered it.

    # Acknowledge load command -> should go to sending.

    pellet_ack_received()

    p_now = time.perf_counter()

    send_begin_age = pellet_machine.get_pellet_send_begin_age(p_now)
    send_end_age = pellet_machine.get_pellet_send_end_age(p_now)

    assert mock_system.pellet_state_trans == [PelletState.sending]
    assert not math.isinf(send_begin_age)
    assert math.isinf(send_end_age)
    assert send_end_age > send_begin_age

    pellet_ack_received()

    send_begin_age = pellet_machine.get_pellet_send_begin_age(p_now)
    send_end_age = pellet_machine.get_pellet_send_end_age(p_now)

    assert not math.isinf(send_begin_age)
    assert not math.isinf(send_end_age)
    assert send_end_age < send_begin_age

    # mock_system.make_load_cell_active()
    machine._analysis.load_cell_monitor.is_engaged = True

    pellet_ack_received()

    assert mock_system.machine_state_trans == [SystemState.tunnel, SystemState.cage, SystemState.tunnel]
    assert mock_system.pellet_state_trans == [PelletState.sending, PelletState.covering]

    assert machine.algorithm.is_in_session is True

    mock_system.make_load_cell_inactive()

    assert machine.algorithm.is_in_session is False

    assert mock_system.machine_state_trans == 2 * [SystemState.tunnel, SystemState.cage]
    # Acknowledge send command -> should go to releasing.
    pellet_ack_received()

    assert machine.algorithm.is_in_session is False

    mock_system.make_load_cell_active()
    mock_system.make_recording_aged_enough()

    assert machine.algorithm.is_in_session is True
    assert machine.pellet.state == PelletState.releasing

    mock_system.make_load_cell_inactive()

    # Acknowledge release command -> should go to monitoring.
    pellet_ack_received()
    assert machine.pellet.state == PelletState.covering

    mock_system.make_load_cell_active()
    mock_system.make_recording_aged_enough()

    assert machine.algorithm.is_in_session is True

    mock_system.make_load_cell_inactive()

    assert machine.algorithm.is_in_session is False

    assert machine.state == SystemState.cage
    assert mock_system.machine_state_trans == 4 * [
        SystemState.tunnel,
        SystemState.cage,
    ]
    assert machine.pellet.state == PelletState.covering
    assert mock_system.pellet_state_trans == [
        PelletState.sending,
        PelletState.covering,
        PelletState.releasing,
        PelletState.monitoring,
        PelletState.covering,
    ]


def test_intersession_enabled(mock_system, machine):
    """
    Placeholder for intersession analysis when ready.  Will not test details of intersession state machine, but that the
    system changes are as expected.
    :return: None
    """
    pellet_machine = machine._pellet_machine

    machine.algorithm.intersession_enabled = True

    assert machine.state == SystemState.cage
    assert machine.algorithm.system_state == machine.state
    assert pellet_machine.state == PelletState.monitoring

    mock_system.make_load_cell_active()  # this trigger a start session recording

    assert pellet_machine.state == PelletState.monitoring

    mock_system.make_recording_aged_enough()

    assert machine.state == SystemState.tunnel
    assert machine.algorithm.system_state == machine.state
    assert pellet_machine.state == PelletState.releasing

    mock_system.mock_pose_response(False, True, ack_pellet=True)

    assert pellet_machine.state == PelletState.monitoring

    with mock_system.mock_perform_segmentation():
        mock_system.make_load_cell_inactive()
        assert not machine._analysis.load_cell_monitor.is_engaged

    assert machine.state == SystemState.intersession
    assert machine.algorithm.system_state == machine.state
    assert mock_system.machine_state_trans == [
        SystemState.tunnel,
        SystemState.cage,
        SystemState.intersession,
    ]
    assert mock_system.pellet_state_trans == [
        PelletState.releasing,
        PelletState.monitoring,
        PelletState.covering,   # double transition
        PelletState.retract,
    ]
    assert pellet_machine._api_status_token is not None, \
        "An API status token should be in use for the previous retract"


def test_inference_detection_ready(machine):
    algo = machine.algorithm
    result = IntersessionResponse(
        food_consumed=20,
        pellet_x=50,
        pellets_presented=40,
        successful_reaches=4,
    )
    assert algo.session_pellet_count == 0
    assert algo.day_pellet_count == 0
    assert algo.successful_reaches_total == 0
    assert algo.pellets_presented_total == 0
    machine._inference.detection_result_ready(result)
    assert algo.session_pellet_count == 20
    assert algo.day_pellet_count == 20
    assert algo.successful_reaches_total == 4
    assert algo.pellets_presented_total == 40
    #
    result.food_consumed = 15
    result.successful_reaches = 2
    result.pellets_presented = 30
    machine._inference.detection_result_ready(result)
    assert algo.session_pellet_count == 35
    assert algo.day_pellet_count == 35
    assert algo.pellets_presented_total == 70
    assert algo.successful_reaches_total == 6


class TestAutoClamp(MockSystemMachine):

    @pytest.mark.parametrize("state", list(SystemState))
    @pytest.mark.parametrize("intensities", [[15, 20, 60], [100], ["base"]])
    @pytest.mark.parametrize("hbp_engaged", [True, False])
    @pytest.mark.parametrize("head_fixation_enabled", [True, False])
    @pytest.mark.parametrize("release_delay", [0.5, 0.1])
    @pytest.mark.parametrize("start_session", [False, True])
    def test_with_analysis_pressure_prop_changed(self, machine, state, intensities, hbp_engaged, head_fixation_enabled,
                                                 release_delay, start_session, mocker):
        machine.state = state
        algo = machine.algorithm

        if start_session:
            algo.start_session()
        assert algo.is_in_session is start_session

        algo.head_fixation_enabled = head_fixation_enabled
        algo.auto_clamp_release_tone_delay = release_delay

        def patch_timer0(delay, func):
            assert delay == algo.auto_clamp_no_activity_release_delay, "the delay should be that"
            m = mock.create_autospec(Timer)
            return m

        analysis = machine._analysis
        tun_dev = machine._tunnel_device
        for idx, intensity in enumerate(intensities):
            if intensity == "base":
                intensity = algo.baseline_intensity
                intensities[idx] = intensity
            algo.auto_clamp_intensity = intensity
            with mock.patch("autotrainer.behavior.system_machine._consider_disengage_autoclamp_timer", new=patch_timer0):
                # if hbp_engaged == analysis.headbar_pressure_monitor.is_engaged:
                #     analysis.headbar_pressure_monitor.is_engaged = not hbp_engaged
                # analysis.headbar_pressure_monitor.is_engaged = hbp_engaged
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
            assert delay == algo.auto_clamp_release_tone_delay, "the delay should be that"
            m = mock.create_autospec(Timer)
            m.start.side_effect = func
            return m

        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch("autotrainer.behavior.system_machine._auto_clamp_release_timer", new=patch_timer))
            stack.enter_context(mock.patch("autotrainer.behavior.system_machine._consider_disengage_autoclamp_timer", new=patch_timer))
            stack.enter_context(mock.patch("autotrainer.behavior.system_machine._consider_end_session_timer", new=patch_timer))
            machine.algorithm.head_fixation_enabled = False  # Disable auto-clamp
        # This above mock patch allow to not have to :
        #   time.sleep(machine.algorithm.auto_clamp_release_delay + 0.0005)
        # and/but not be always sure that the timer has completed...
        # NB:
        # This is eventually fragile if other Timer (than the exact one desired (in the same module that is)) were
        #  created during the same code execution.

        # Now ensure update_head_magnet_intensity has been called as desired (or not):
        if head_fixation_enabled:
            exp_update_head_magnet = [mock.call(machine.algorithm.baseline_intensity)]
            if start_session:
                exp_play_tone = [
                    mock.call(machine.algorithm.auto_clamp_release_tone_freq, 0.5)
                ]
            else:
                exp_play_tone = []
        else:
            exp_update_head_magnet = exp_play_tone = []
        #
        assert tun_dev.update_head_magnet_intensity.call_args_list == exp_update_head_magnet
        assert machine._pellet_device.play_tone.call_args_list == exp_play_tone

    # 2025-05-18 Turning auto-clamp off at session end has been removed for the time being.  This may change once
    # auto-clamp is fully evaluated w/animals.
    @pytest.mark.parametrize("start_session", [False, True])
    def test_auto_clamp_session_off_reset_to_baseline(self, machine, start_session):
        machine.state = SystemState.tunnel
        if start_session:
            machine.algorithm.start_session()
        tun_dev = machine._tunnel_device
        assert tun_dev.update_head_magnet_intensity.call_args_list == []
        #
        # used with debugger:
        # def catch(*args, **kwargs):
        #     pass
        # tun_dev.update_head_magnet_intensity.side_effect = catch
        machine.after_exit_tunnel()

        assert tun_dev.update_head_magnet_intensity.call_args_list == [
            mock.call(machine.algorithm.baseline_intensity)
        ]
        assert machine._pellet_device.play_tone.call_args_list == []

    @pytest.mark.parametrize("feature_enabled", [False, True])
    def test_clean_raw_data_on_session_end(self, machine, project_info, feature_enabled):
        machine.project = project_info
        machine.algorithm.start_session()
        machine.algorithm.intersession_enabled = True
        # check with cam1 file paths:
        cam = project_info.camera_1
        file_paths = list(
            map(Path, chain(project_info.get_video_path(cam), [
                project_info.get_intersession_pose_path(cam, suffix="_live")]))
        )
        assert len(file_paths) > 0
        for p in file_paths:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.touch()
        machine.algorithm.clean_raw_data_on_inactive_session = feature_enabled
        def patch_timer(delay, func):
            m = mock.create_autospec(Timer)
            m.start.side_effect = func
            return m
        with mock.patch("autotrainer.behavior.system_machine._clean_raw_data_timer", new=patch_timer):
            machine.algorithm.end_session()
        for p in file_paths:
            assert not p.exists() if feature_enabled else p.exists()

    #

class TestSessionProcessingEnding(MockSystemMachine):

    def test_when_no_intersession(self, machine):
        processing_ended_count = 0
        def processing_ended(status):
            nonlocal processing_ended_count
            processing_ended_count += 1
            assert status == CaptureAnalysisResult.CAPTURE_ONLY
        #
        algo = machine.algorithm
        algo.intersession_enabled = False
        algo.session_processing_ending += processing_ended
        algo.start_session()
        assert processing_ended_count == 0
        algo.end_session()
        assert processing_ended_count == 1

    def test_when_intersession_mouse_not_seen(self, machine):
        processing_ended_count = 0
        def processing_ended(status):
            nonlocal processing_ended_count
            processing_ended_count += 1
            assert status == CaptureAnalysisResult.CAPTURE_ONLY
        #
        algo = machine.algorithm
        algo.intersession_enabled = True
        algo.session_processing_ending += processing_ended
        #
        algo.start_session()
        assert processing_ended_count == 0
        algo.update_mouse_seen(False)
        assert processing_ended_count == 0
        algo.end_session()
        assert processing_ended_count == 1

    @pytest.mark.parametrize("detection_success", [False, True])
    def test_when_intersession_mouse_seen(self, machine, detection_success):
        processing_ended_count = 0
        def processing_ended(status):
            nonlocal processing_ended_count
            processing_ended_count += 1
            assert status == (
                CaptureAnalysisResult.ANALYSIS_SUCCEEDED if detection_success
                else CaptureAnalysisResult.ANALYSIS_FAILED
            )

        #
        algo = machine.algorithm
        algo.intersession_enabled = True
        algo.session_processing_ending += processing_ended
        algo.start_session()
        algo.update_mouse_seen(True)
        assert processing_ended_count == 0
        with contextlib.ExitStack() as stack:
            stack.enter_context(self.mock_perform_segmentation())
            assert processing_ended_count == 0
            stack.enter_context(self.mock_perform_detection())
            assert processing_ended_count == 0
            algo.end_session()
            assert processing_ended_count == 0
            self.mock_complete_segmentation(True)
            assert processing_ended_count == 0
            self.mock_complete_detection(detection_success)
            assert processing_ended_count == 1
        assert processing_ended_count == 1

    def test_when_intersession_mouse_seen_segmentation_fails(self, machine):
        processing_ended_count = 0
        def processing_ended(status):
            nonlocal processing_ended_count
            processing_ended_count += 1
            assert status == CaptureAnalysisResult.ANALYSIS_FAILED
        #
        algo = machine.algorithm
        algo.intersession_enabled = True
        algo.session_processing_ending += processing_ended
        algo.start_session()
        algo.update_mouse_seen(True)
        assert processing_ended_count == 0
        with contextlib.ExitStack() as stack:
            stack.enter_context(self.mock_perform_segmentation())
            assert processing_ended_count == 0
            algo.end_session()
            assert processing_ended_count == 0
            self.mock_complete_segmentation(False)
            assert processing_ended_count == 1
        assert processing_ended_count == 1
