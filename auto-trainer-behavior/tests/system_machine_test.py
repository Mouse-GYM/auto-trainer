import contextlib
import logging
import math
import time
from itertools import chain
from pathlib import Path
from threading import Timer
from unittest import mock

import pytest

from autotrainer.core.pose_elements import SceneElement
from autotrainer.core.video_detection import PresenceDetectionAttrs
from autotrainer.inference import PoseResponse, PoseLocation

from top_fixtures import MockSystemMachine


from autotrainer.core import HeadbarPressureMonitor, get_perf_now, Offset3DTuple
from autotrainer.core import Notification, TriggerNotification, NotificationCenter

from autotrainer.behavior import CaptureAnalysisResult, IntersessionState
from autotrainer.behavior import SystemState, SystemMachine
from autotrainer.behavior.pellet import PelletState
from autotrainer.behavior.pellet.pellet_machine import PelletMachine

from autotrainer.inference.analysis.intersession_process import IntersessionResponse


def test_enter_exit_tunnel(mock_system, machine):
    algo = machine.algorithm

    # Observe for video capture being triggered.
    is_capture_triggered = False

    def set_capture_triggered(notification: Notification):
        nonlocal is_capture_triggered
        is_capture_triggered = notification.context

    NotificationCenter.default_center().add_observer(TriggerNotification.CAPTURE_ID, set_capture_triggered)

    # Current code assumes intersession analysis is off by default.
    assert algo.intersession_enabled is False

    # Defaults
    assert machine.state == SystemState.cage
    assert algo.is_in_session is False
    assert not algo.pellet_recently_seen
    algo.update_pellet_seen(True)
    assert algo.pellet_recently_seen
    assert is_capture_triggered is False

    # Should trigger enter tunnel, new session, and associated changes.
    mock_system.make_load_cell_active()

    assert algo.is_in_session is True
    assert is_capture_triggered is True
    assert machine.state == SystemState.tunnel

    mock_system.make_load_cell_inactive()

    assert machine.state == SystemState.cage
    assert algo.is_in_session is False
    assert is_capture_triggered is False
    assert mock_system.machine_state_trans == [
        SystemState.tunnel,
        SystemState.cage,
    ]


def test_no_session_without_pellet(mock_system, machine: SystemMachine):
    pellet_m = machine._pellet_machine
    algo = machine.algorithm
    assert isinstance(pellet_m, PelletMachine)

    load_attempt_count = load_ok_count = 0
    def pellet_loading():
        nonlocal load_attempt_count
        load_attempt_count += 1

    def pellet_loaded():
        nonlocal load_ok_count
        load_ok_count += 1

    pellet_m.events.pellet_loading += pellet_loading
    pellet_m.events.pellet_loaded += pellet_loaded

    # before:
    assert algo.is_in_session is False
    assert load_attempt_count == 0
    assert not algo.triangle_recently_seen
    assert not algo.pellet_recently_seen

    # Lose the pellet (pellet state machine initializes to monitoring).  Pellet machine will be in loading state.
    mock_system.mock_pose_response(pellet_seen=False, triangle_seen=True)
    # NB: on very first start the pellet_last_seen will be -inf.. so that the first load will not have to wait pellet_missing_time:
    assert load_attempt_count == 1
    assert mock_system.pellet_state_trans == [PelletState.loading]
    assert algo.triangle_recently_seen
    assert not algo.pellet_recently_seen

    mock_system.pellet_state_trans.clear()

    # if ack the load-pellet, and pellet not  yet seen, then
    assert pellet_m._api_status_token is not None
    mock_system.mock_pellet_ack()
    assert load_attempt_count == 2
    assert mock_system.pellet_state_trans == []
    assert pellet_m._api_status_token is not None
    # pellet must be seen after loading to go to sending
    mock_system.mock_pose_response(pellet_seen=True)
    mock_system.mock_pellet_ack()  # ack the loading
    assert mock_system.pellet_state_trans == [
        PelletState.covering,
        PelletState.sending,
        PelletState.monitoring,
    ]
    mock_system.pellet_state_trans.clear()
    mock_system.mock_pellet_ack()  # ack the sending, covering is included.
    assert pellet_m._api_status_token is None

    assert mock_system.machine_state_trans == []

    mock_system.mock_pose_response(pellet_seen=False)
    assert pellet_m.state == PelletState.monitoring, "must wait missing time before load"
    mock_system.increment_perf_now(algo.pellet_missing_time)

    assert pellet_m.state == PelletState.monitoring

    mock_system.make_load_cell_active()
    assert algo.is_in_session is False, "without a pellet-seen session must not start"
    assert pellet_m.state == PelletState.monitoring  # still monitoring
    assert machine.state == SystemState.tunnel  # but tunnel

    # now:
    mock_system.mock_pose_response(pellet_seen=False)
    assert pellet_m.state == PelletState.loading

    assert not algo.pellet_recently_seen
    mock_system.mock_pose_response(pellet_seen=True)  # make pellet-seen
    assert algo.pellet_recently_seen

    mock_system.mock_pellet_ack()  # ack the loading AFTER put pellet_seen

    assert algo.is_in_session is False
    assert algo.pellet_recently_seen

    assert pellet_m.state == PelletState.monitoring
    assert mock_system.pellet_state_trans == [
        PelletState.loading,
        PelletState.covering,
        PelletState.sending,
        PelletState.monitoring,
    ]

    mock_system.mock_pellet_ack()  # ack the sending, covering is included.

    assert algo.pellet_recently_seen
    assert algo.is_in_session is True, "Once pellet seen and send acked and in monitoring"

    mock_system.make_load_cell_inactive()

    assert not algo.is_in_session
    assert algo.pellet_recently_seen
    assert mock_system.machine_state_trans == [SystemState.tunnel, SystemState.cage]
    mock_system.machine_state_trans.clear()

    mock_system.make_load_cell_active()

    assert algo.pellet_recently_seen

    assert mock_system.machine_state_trans == [SystemState.tunnel]

    assert algo.is_in_session is True, "now that pellet-seen: is_in_session"

    mock_system.make_load_cell_inactive()

    assert algo.is_in_session is False
    assert mock_system.machine_state_trans == [SystemState.tunnel, SystemState.cage]


def test_intersession_enabled(mock_system, machine):
    """
    Placeholder for intersession analysis when ready.  Will not test details of intersession state machine, but that the
    system changes are as expected.
    :return: None
    """
    algo = machine.algorithm
    pellet_m = machine._pellet_machine

    algo.intersession_enabled = True
    algo.pellet_cover_enabled = True

    assert machine.state == SystemState.cage
    assert algo.system_state == machine.state
    assert pellet_m.state == PelletState.monitoring

    mock_system.mock_pose_response(pellet_seen=True)

    # first pellet-seen make the pellet to be covered:
    assert mock_system.pellet_state_trans == [
        PelletState.covering,
        PelletState.monitoring,
    ]
    mock_system.pellet_state_trans.clear()
    assert pellet_m._api_status_token is None  # but we don't await the cover ack

    mock_system.make_load_cell_active()  # this trigger a start session recording

    assert algo.is_in_session
    assert pellet_m.state == PelletState.monitoring
    assert machine.state == SystemState.tunnel
    assert algo.system_state == machine.state
    assert pellet_m.state == PelletState.monitoring

    mock_system.mock_pose_response(pellet_seen=False, mouse_seen=True, ack_pellet=True)

    assert pellet_m.state == PelletState.monitoring

    with mock_system.mock_perform_segmentation():
        mock_system.make_load_cell_inactive()
        assert not machine._analysis.load_cell_monitor.is_engaged

    assert algo.intersession_state == IntersessionState.segmentation
    assert machine.state == SystemState.intersession
    assert algo.system_state == machine.state
    assert mock_system.machine_state_trans == [
        SystemState.tunnel,
        SystemState.cage,
        SystemState.intersession,
    ]
    assert mock_system.pellet_state_trans == [
        PelletState.retract,
    ]
    assert pellet_m._api_status_token is not None, \
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


@pytest.mark.parametrize("feature_enabled", [False, True])
def test_clean_raw_data_on_session_end(machine, project_info, feature_enabled):
    algo = machine.algorithm
    machine.project = project_info
    algo.start_session()
    algo.intersession_enabled = True
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
    algo.clean_raw_data_on_inactive_session = feature_enabled
    def patch_timer(delay, func):
        m = mock.create_autospec(Timer)
        m.start.side_effect = func
        return m
    with mock.patch("autotrainer.behavior.system_machine._clean_raw_data_timer", new=patch_timer):
        algo.end_capture_session()
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
        algo.session_ending += processing_ended
        algo.start_session()
        assert processing_ended_count == 0
        algo.end_capture_session()
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
        algo.session_ending += processing_ended
        #
        algo.start_session()
        assert processing_ended_count == 0
        algo.update_mouse_seen(False)
        assert processing_ended_count == 0
        algo.end_capture_session()
        assert processing_ended_count == 1

    @pytest.mark.parametrize("detection_success", [False, True])
    @pytest.mark.parametrize("system_state", [SystemState.cage, SystemState.tunnel])
    def test_when_intersession_mouse_seen(self, machine, detection_success, system_state):
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
        algo.session_ending += processing_ended
        algo.start_session()
        algo.update_mouse_seen(True)
        assert processing_ended_count == 0
#         with self.mock_analysis(detection_ok=detection_success):
        with contextlib.ExitStack() as stack:
            stack.enter_context(self.mock_perform_segmentation())
            assert processing_ended_count == 0
            stack.enter_context(self.mock_perform_detection())
            assert processing_ended_count == 0
            machine.state = system_state
            algo.end_capture_session()
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
        algo.session_ending += processing_ended
        algo.start_session()
        algo.update_mouse_seen(True)
        assert processing_ended_count == 0
        with contextlib.ExitStack() as stack:
            stack.enter_context(self.mock_perform_segmentation())
            assert processing_ended_count == 0
            algo.end_capture_session()
            assert processing_ended_count == 0
            self.mock_complete_segmentation(False)
            assert processing_ended_count == 1
        assert processing_ended_count == 1


def test_handle_diamond_triangle_offset_full(mock_system, machine):
    self = mock_system
    algo = machine.algorithm
    algo.reload_diamond_triangle_config()  # ensure it's loaded
    machine.enter_tunnel()
    pellet_m = machine.pellet
    diamond_cfg = machine.algorithm.diamond_triangle_config
    assert machine.state == SystemState.tunnel
    assert pellet_m.state == PelletState.monitoring
    assert pellet_m.can_use_pellet_command()
    #
    last_pos = pellet_m._pellet_device.last_position = diamond_cfg.used_position  # noqa
    inference_pos = diamond_cfg.motor_to_inference(last_pos)
    # diamond_cfg.inference_to_motor()
    rsp_idx = 0
    se = SceneElement
    locs_3d = {
        se.Diamond: inference_pos + diamond_cfg.measured_offset,
        se.Triangle: diamond_cfg.measured_offset,
    }
    presents = {se.Diamond: True, se.Triangle: True, se.Pellet: True}  # keep pellet seen

    def make_rsp():
        nonlocal rsp_idx
        parts_offset = {
            se.Diamond: {
                se.Triangle: locs_3d[se.Diamond] - locs_3d[se.Triangle],
            }
        }
        locs = []  # 2d inference location unnecessary
        r = PoseResponse(
            sequence=rsp_idx,
            parts_flags=(presents, presents, presents),
            locations=locs,
            locations_3d=locs_3d,
            parts_3d_offsets=parts_offset,
        )
        rsp_idx += 1
        return r
    #
    def pose_changed():
        machine._pose_changed(make_rsp())
    #
    assert algo.get_diamond_triangle_drifts() is None
    pose_changed()
    assert algo.get_diamond_triangle_drifts() == (0, 0, 0)
    locs_3d[se.Triangle] += (0.5, 1, -1)
    pose_changed()
    assert algo.get_diamond_triangle_drifts() == (0.25, -0.5, -0.5)  # given 2 measures now
    pose_changed()
    assert algo.get_diamond_triangle_drifts(reset=True) == (1 / 3, -2 / 3, -2 / 3)  # given 3 measures now
    assert algo.get_diamond_triangle_drifts() is None
    #
    presents.pop(se.Pellet)
    self.increment_perf_now(algo.pellet_missing_time)
    pose_changed()
    assert algo.get_diamond_triangle_drifts(reset=True) is not None
    pose_changed()
    assert algo.get_diamond_triangle_drifts() is None  # given in loading now
    presents[se.Pellet] = True
    pose_changed()
    self.mock_pellet_ack()  # ack load
    pose_changed()
    assert algo.get_diamond_triangle_drifts() is None  # given in sending now
    assert pellet_m.state == PelletState.monitoring  # even if already monitoring
    assert not pellet_m.can_use_pellet_command()  # sending not finished
    self.mock_pellet_ack()  # ack send
    assert pellet_m.state == PelletState.monitoring  # still
    assert pellet_m.can_use_pellet_command()
    pose_changed()
    assert algo.get_diamond_triangle_drifts() == (0.5, -1, -1)  # back
