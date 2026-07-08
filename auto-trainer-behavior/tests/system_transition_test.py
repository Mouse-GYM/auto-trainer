"""
Test transition behavior with explicit calls to the transitions and the behavior algorithm state only.  Transitions that
would/should happen due to external input (devices, pose information) are tested elsewhere.  These tests do not require
mocks or real interfaces.
"""
from unittest import mock

import pytest
from transitions import MachineError

from autotrainer.behavior import SystemState, SystemMachine


def test_enter_exit_transitions(machine: SystemMachine, mock_system):
    # Current code assumes intersession analysis is off by default.  Flag if that changes and we forget to update
    # assumptions.
    algo = machine.algorithm
    # some defaults:
    assert algo.intersession_enabled is False
    assert machine.state == SystemState.cage

    with pytest.raises(MachineError):
        machine.exit_intersession_to_cage(algo.project)

    with pytest.raises(MachineError):
        machine.exit_tunnel()

    algo.update_pellet_seen(True)  # required for below

    machine.enter_tunnel()

    assert machine.state == SystemState.tunnel

    machine.exit_tunnel()

    assert machine.state == SystemState.cage

    algo.intersession_enabled = True

    machine._analysis.load_cell_monitor.is_engaged = True

    assert algo.is_in_session
    assert machine.state == SystemState.tunnel

    algo.update_mouse_seen(True)  # required for intersession analysis !!

    with mock_system.mock_perform_segmentation() as m_perf_segm:
        assert m_perf_segm.call_args_list == []
        machine.exit_tunnel()

    assert m_perf_segm.call_args_list == [
        mock.call(machine.intersession._segmentation_configuration)
    ]

    # Test with intersession enabled.
    assert machine.state == SystemState.intersession

    with pytest.raises(MachineError):
        machine.enter_tunnel()

    with pytest.raises(MachineError):
        machine.exit_tunnel()

    machine.exit_intersession_to_cage(algo.project)

    assert machine.state == SystemState.cage
