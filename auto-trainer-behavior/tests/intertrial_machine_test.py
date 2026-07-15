import contextlib
import datetime
import logging
from unittest import mock

import pytest
from autotrainer.api import ApiEventKind

from autotrainer.core import ProjectInfo, EventManager, EventInfo
from transitions import MachineError

from autotrainer.behavior import SegmentationConfiguration, DetectionConfiguration, SystemState
from autotrainer.behavior.intertrial import IntertrialState
from autotrainer.inference.analysis import IntertrialResponse


def test_intertrial(
    mock_system,
    machine,
):
    intertrial = machine.intertrial

    project = machine.project
    assert project is not None
    assert intertrial.state == IntertrialState.idle

    with pytest.raises(MachineError):
        seg_cfg = SegmentationConfiguration(
            project=project,
            complete=lambda s: 1 / 0,  # noqa
        )
        intertrial.perform_detection(seg_cfg)

    machine.state = SystemState.intertrial

    def during_segm():
        assert intertrial.state == IntertrialState.segmentation

    def during_detection():
        assert intertrial.state == IntertrialState.detection

    with mock_system.mock_analysis(seg_conc_func=during_segm, det_conc_func=during_detection):
        assert intertrial.state == IntertrialState.idle
        intertrial.perform_segmentation(project)
        assert intertrial.state == IntertrialState.segmentation

    assert intertrial.state == IntertrialState.idle

    assert mock_system.intertrial_state_trans == [
        IntertrialState.segmentation,
        IntertrialState.detection,
        IntertrialState.idle,
    ]


def test_intertrial_increase_algo_counts(mock_system):
    algo = mock_system.algo
    algo.intertrial_enabled = True
    mock_system.mock_pose_response(pellet_seen=True)
    mock_system.start_trial_in_tunnel(set_recording_status=True)
    assert algo.is_in_trial_capture
    algo.update_mouse_seen(True)
    res = IntertrialResponse(
        pellets_presented=4,
        total_reaches=3,
        food_consumed=2,
        successful_reaches=1,
    )
    with mock_system.mock_analysis(detection_result=res):
        mock_system.exit_tunnel()
    assert algo.pellets_presented_day == algo.pellets_presented_total == 0  # NB: this now accounts for pellet-sent event
    assert algo.pellet_reaches_day == algo.pellet_reaches_total == 3
    assert algo.pellet_consumed_day == algo.pellet_consumed_total == 2
    assert algo.successful_reaches_day == algo.successful_reaches_total == 1


def test_exit_tunnel_when_analysis_ongoing(mock_system, machine, caplog):
    algo = mock_system.algo
    algo.intertrial_enabled = True
    machine._delay_timer_consider_end_trial = 0  # simpler test
    #
    after_exit_tunnel_msg = "after_exit_tunnel: load_cell_disengaged_intertrial_in_progress"

    mock_system.start_trial_in_tunnel()
    mock_system.mock_pose_response(pellet_seen=True, mouse_seen=True, triangle_seen=True)

    mock_system.mock_event_manager()
    has_event = mock_system.has_event

    def perform_exit_tunnel():
        assert machine.state == SystemState.intertrial
        assert not has_event(ApiEventKind.tunnelExit)
        mock_system.exit_tunnel()
        assert has_event(ApiEventKind.tunnelExit)
        assert machine.state == SystemState.intertrial
        assert after_exit_tunnel_msg in caplog.text
        assert not has_event(ApiEventKind.sessionEnded), \
            "sessionEnded will only be emitted after the intertrial is finished"

    with caplog.at_level(logging.DEBUG):
        with mock_system.mock_analysis(seg_conc_func=perform_exit_tunnel):
            assert machine.state == SystemState.tunnel
            mock_system.mock_pose_response(pellet_seen=False, mouse_seen=True, triangle_seen=True)
            mock_system.mock_pellet_ack(until_none=True)
            mock_system.increment_perf_now(algo.pellet_missing_time)
            mock_system.mock_pose_response(pellet_seen=False, mouse_seen=True, triangle_seen=True)
            assert machine.state == SystemState.intertrial
            assert after_exit_tunnel_msg not in caplog.text

    assert machine.state == SystemState.cage, "Must be back in cage after end intertrial analysis"
    assert after_exit_tunnel_msg in caplog.text
    assert has_event(ApiEventKind.sessionEnded), "Now that intertrial is finished sessionEnded must also be posted"
