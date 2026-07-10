from unittest import mock

import pytest

from top_fixtures import MockSystemMachine, AlmostEqualFloat


class TestRecordPrebufferDuration(MockSystemMachine):

    @pytest.mark.parametrize("prerecord_duration", [-5, 0])
    def test_it_start_trial_with_zero_or_negative(self, machine, caplog, prerecord_duration):
        algo = self.algo
        algo.record_prebuffer_duration = prerecord_duration
        algo.update_pellet_seen(True)
        machine.pellet.send_pellet()
        self.mock_pellet_ack(until_none=True)
        half = prerecord_duration / 2
        self.increment_perf_now(half)
        algo.update_pellet_seen(True)
        with self.patch_timer(f"{machine.__class__.__module__}._consider_start_trial_timer") as m_timer:
            self.sensor_analysis.load_cell_monitor.is_engaged = True
        assert algo.is_in_trial_capture
        assert m_timer.call_args_list == []

    @pytest.mark.parametrize("prerecord_duration", [0.4, 2.5])
    def test_it_start_trial_with_positive_duration(self, machine, caplog, prerecord_duration):
        algo = self.algo
        algo.record_prebuffer_duration = prerecord_duration
        algo.update_pellet_seen(True)
        machine.pellet.send_pellet()
        self.mock_pellet_ack(until_none=True)
        half = prerecord_duration / 2
        self.increment_perf_now(half)
        algo.update_pellet_seen(True)
        with self.patch_timer(f"{machine.__class__.__module__}._consider_start_trial_timer") as m_timer:
            self.sensor_analysis.load_cell_monitor.is_engaged = True
        assert algo.is_in_trial_capture
        assert m_timer.call_args_list == []
