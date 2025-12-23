import logging
from datetime import datetime
from unittest import mock

import pytest

from autotrainer.behavior import PelletState, SystemState, PelletMachine, PelletDeviceProtocol, BehaviorAlgorithm, \
    SystemMachine

from top_fixtures import MockSystemMachine, mock_system


@pytest.mark.parametrize("cover_enabled", [False, True])
def test_cover_or_release_pellet_on_load_pellet(mock_system, machine, cover_enabled):
    """
    Should confirm that:
        A missing pellet triggers load in and out of tunnel
        Pellet is released under all conditions
    :return: None
    """
    pellet_m = machine.pellet
    algo = machine.algorithm

    algo.pellet_cover_enabled = cover_enabled

    algo.update_pellet_seen(True)
    algo.update_triangle_seen(True)

    assert machine.state == SystemState.cage
    assert not algo.is_in_session
    assert algo.pellet_recently_seen

    # Send a pose response with pellet not seen which should trigger a load/cover cycle while out of tunnel.
    mock_system.mock_pose_response(pellet_seen=False)
    assert pellet_m.state == PelletState.monitoring  # still
    assert algo.pellet_recently_seen  # still
    mock_system.increment_perf_now(algo.pellet_missing_time + 1e-9)
    assert not algo.pellet_recently_seen  # now not recently seen
    mock_system.mock_pose_response(pellet_seen=False)
    assert pellet_m.state == PelletState.loading
    mock_system.increment_perf_now(1e-9)
    mock_system.mock_pose_response(pellet_seen=True)
    mock_system.increment_perf_now(1e-9)
    mock_system.mock_pellet_ack()  # ack the load
    assert pellet_m.state == PelletState.monitoring
    assert mock_system.pellet_state_trans == [
        PelletState.loading,
        PelletState.covering if cover_enabled else PelletState.releasing,
        PelletState.sending,
        PelletState.monitoring
    ]
    mock_system.mock_pellet_ack()  # ack the send
    assert algo.can_cover_pellet() is (True if cover_enabled else False)
    assert algo.can_release_pellet() is (False if cover_enabled else True)
    assert algo.session_pellet_count == 0
    mock_system.mock_pose_response(pellet_seen=True)
    assert algo.pellet_recently_seen
    assert algo.session_pellet_count == 1


def test_uncover_when_record_aged_enough(mock_system, machine):
    pellet_m = machine.pellet
    algo = machine.algorithm
    algo.pellet_cover_enabled = True
    load_cell = machine._analysis.load_cell_monitor
    algo.update_pellet_seen(True)
    algo.update_triangle_seen(True)
    assert pellet_m.state == PelletState.monitoring
    assert not algo.is_in_session

    load_cell.is_engaged = True
    assert algo.is_in_session
    assert pellet_m.state == PelletState.monitoring
    assert mock_system.pellet_state_trans == []
    # now:
    mock_system.make_recording_aged_enough()
    # and:
    pellet_m.environment_changed()
    assert mock_system.pellet_state_trans == [
        PelletState.releasing,
        PelletState.monitoring,
    ]
    assert pellet_m._api_status_token is None, "we don't await the release"


def test_uncover_when_hands_near_pellet(mock_system, machine):
    pellet_m = machine.pellet
    algo = machine.algorithm
    algo.pellet_cover_enabled = True
    algo.pellet_hand_uncover_distance = 5
    load_cell = machine._analysis.load_cell_monitor
    algo.update_pellet_seen(True)
    algo.update_triangle_seen(True)
    load_cell.is_engaged = True
    assert algo.is_in_session
    mock_system.make_recording_aged_enough()
    assert pellet_m.state == PelletState.monitoring
    assert mock_system.pellet_state_trans == [], "contrary to test_uncover_when_record_aged_enough"
    algo.pellet_hands_min_distance = algo.pellet_hand_uncover_distance
    assert pellet_m.state == PelletState.monitoring
    assert mock_system.pellet_state_trans == [
        PelletState.releasing,
        PelletState.monitoring,
    ]
    assert pellet_m._api_status_token is None, "we don't await the release ack"


@pytest.mark.skipif(True, reason="Session limits and associated logic currently on hold")
def test_session_limit(mock_system, machine):
    # TODO: Session limits and associated logic currently on hold.
    pass


@pytest.mark.skipif(True, reason="Disabled until day limit is implemented via reach detection.")
def test_day_limit(machine, mock_system):
    # TODO
    pass
