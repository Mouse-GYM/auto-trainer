"""
Test transition behavior with explicit calls to the transitions and the behavior algorithm state only.  Transitions that
would/should happen due to external input (devices, pose information) are tested elsewhere.  These tests do not require
mocks or real interfaces.
"""
from unittest import mock

import pytest
from transitions import MachineError

from autotrainer.behavior import SystemState


def test_enter_exit_transitions(machine, mock_system):
    # Current code assumes intersession analysis is off by default.  Flag if that changes and we forget to update
    # assumptions.
    assert machine.algorithm.intersession_enabled is False

    assert machine.state == SystemState.cage

    with pytest.raises(MachineError):
        machine.exit_intersession()

    with pytest.raises(MachineError):
        machine.exit_tunnel()

    machine.enter_tunnel()

    assert machine.state == SystemState.tunnel

    with pytest.raises(MachineError):
        machine.enter_intersession()

    with pytest.raises(MachineError):
        machine.exit_intersession()

    machine.exit_tunnel()

    assert machine.state == SystemState.cage

    machine.algorithm.intersession_enabled = True

    machine.enter_tunnel()

    assert machine.state == SystemState.tunnel

    machine.algorithm.mouse_seen(True)

    with mock_system.mock_perform_segmentation() as m_perf_segm:
        machine.exit_tunnel()

    assert m_perf_segm.call_args_list == [mock.call(machine.intersession._segmentation_configuration)]

    # Test with intersession enabled.
    assert machine.state == SystemState.intersession

    with pytest.raises(MachineError):
        machine.enter_tunnel()

    with pytest.raises(MachineError):
        machine.exit_tunnel()

    machine.exit_intersession()

    assert machine.state == SystemState.cage
