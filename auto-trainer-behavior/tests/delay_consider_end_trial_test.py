from unittest import mock

import pytest

from autotrainer.core.interfaces import RecordingEndingReason
from top_fixtures import MockSystemMachine, AlmostEqualFloat


class TestDelayConsiderEndTrial(MockSystemMachine):
    """NB: this delay is only applied/taken into account for pellet-loading event"""

    @pytest.mark.parametrize("delay", [-1, 0])
    def test_it_does_not_delay_with_zero_or_negative(self, machine, caplog, delay):
        algo = self.algo
        machine._delay_timer_consider_end_trial = delay
        algo.update_pellet_seen(True)
        self.start_trial_in_tunnel()
        with self.patch_timer(f"{machine.__class__.__module__}._consider_end_trial_timer") as m_timer:
            machine.pellet.load_pellet(force=True)
        assert m_timer.call_args_list == []
        assert not algo.is_in_trial_capture

    @pytest.mark.parametrize("delay", [0.15, 2])
    def test_it_delays_end_trial_with_positive_value(self, machine, caplog, delay):
        algo = self.algo
        machine._delay_timer_consider_end_trial = delay
        algo.update_pellet_seen(True)
        self.start_trial_in_tunnel()
        with self.patch_timer(f"{machine.__class__.__module__}._consider_end_trial_timer") as m_timer:
            machine.pellet.load_pellet(force=True)
        assert algo.is_in_trial_capture
        assert m_timer.call_args_list == [mock.call(AlmostEqualFloat(delay), mock.ANY)]
        self.increment_perf_now(delay)
        func = m_timer.call_args.args[1]
        func()
        assert not algo.is_in_trial_capture

    @pytest.mark.parametrize("delay", [0.15, 2])
    def test_it_does_not_cancel_prev_timer_on_pellet_reload(self, machine, caplog, delay):
        algo = self.algo
        machine._delay_timer_consider_end_trial = delay
        algo.update_pellet_seen(True)
        self.start_trial_in_tunnel()
        with self.patch_timer(f"{machine.__class__.__module__}._consider_end_trial_timer") as m_timer:
            machine.pellet.load_pellet(force=True)
        assert m_timer.call_args_list == [mock.call(AlmostEqualFloat(delay), mock.ANY)]
        func = m_timer.call_args.args[1]
        self.increment_perf_now(delay)
        assert algo.is_in_trial_capture
        with self.patch_timer(f"{machine.__class__.__module__}._consider_end_trial_timer") as m_timer2:
            machine.pellet.load_pellet(force=True)
        assert m_timer2.call_args_list == []
        assert m_timer.return_value.cancel.call_args_list == []
        func()
        assert not algo.is_in_trial_capture

    def test_it_does_not_consider_if_not_in_trial(self, machine, caplog):
        algo = self.algo
        assert not algo.is_in_trial_capture
        with self.patch_timer(f"{machine.__class__.__module__}._consider_end_trial_timer") as m_timer2:
            machine._consider_end_trial(reason=RecordingEndingReason.PELLET_LOADING)
        assert "consider_end_session: reason=PelletLoading but not in session"
