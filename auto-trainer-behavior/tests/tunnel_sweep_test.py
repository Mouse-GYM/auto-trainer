import datetime
import logging
from datetime import timedelta
from unittest import mock
from unittest.mock import call

import pytest

from autotrainer.core.configuration.behavior_configuration import TimePeriod
from top_fixtures import MockSystemMachine, AlmostEqualFloat

from autotrainer.behavior import SystemState, SystemMachine


class TestAutoTunnelSweep(MockSystemMachine):

    @property
    def tunnel_sweep(self):
        return self.sensor_analysis.auto_tunnel_sweep_monitor

    def _init(self, machine: SystemMachine):
        super()._init(machine)
        # self.sensor_analysis.pellet_misplaced_monitor.start()
        sweep = self.tunnel_sweep
        sweep.config.enabled = True
        sweep.config.misplaced_trigger_delay = 0
        sweep.start()

    @pytest.mark.parametrize("start_trial", [False, True])
    @pytest.mark.parametrize("fan_dur", [3, 10])
    def test_it_triggers_with_pellet_misplaced_and_disengage_after_delay(
        self,
        caplog,
        start_trial,
        fan_dur,
    ):
        sweep = self.tunnel_sweep
        sweep.config.tunnel_fan_on_duration = fan_dur
        misplaced = self.sensor_analysis.pellet_misplaced_monitor
        pellet_dev = self.pellet_dev
        tunnel_dev = self.tunnel_dev
        if start_trial:
            self.start_trial_in_tunnel()
        assert not sweep.is_engaged
        with caplog.at_level(logging.DEBUG):
            misplaced.is_engaged = True
        assert sweep.is_engaged
        assert call.open_tunnel_gate() in tunnel_dev.method_calls
        assert call.set_tunnel_fan_on() in pellet_dev.method_calls
        assert pellet_dev.set_tunnel_fan_off.call_args_list == []
        pellet_dev.reset_mock()
        half_fan_on_dur = sweep.config.tunnel_fan_on_duration / 2
        self.increment_perf_now(half_fan_on_dur)
        assert AlmostEqualFloat(half_fan_on_dur) == sweep.check_state()
        assert pellet_dev.set_tunnel_fan_off.call_args_list == []
        assert sweep.is_engaged
        self.increment_perf_now(half_fan_on_dur)
        r = sweep.check_state()
        assert r == sweep.default_timer_delay
        assert not sweep.is_engaged
        assert call.set_tunnel_fan_off() in pellet_dev.method_calls

    @pytest.mark.parametrize("trigger_delay", [3, 5])
    def test_with_trigger_delay(self, trigger_delay, caplog):
        sweep = self.tunnel_sweep
        sweep.config.misplaced_trigger_delay = trigger_delay
        misplaced = self.sensor_analysis.pellet_misplaced_monitor
        with mock.patch.object(sweep, "_make_new_timer") as m_new_timer:
            misplaced.is_engaged = True
        assert not sweep.is_engaged
        assert m_new_timer.call_args_list == [mock.call(AlmostEqualFloat(trigger_delay))]
        misplaced.is_engaged = False
        # ensure a new timer is created after:
        with mock.patch.object(sweep, "_make_new_timer") as m_new_timer:
            misplaced.is_engaged = True
        assert m_new_timer.call_args_list == [mock.call(AlmostEqualFloat(trigger_delay))]

    @pytest.mark.parametrize("rate_limit_delay", [15, 30])
    def test_rate_limit_delay(self, rate_limit_delay, caplog):
        sweep = self.tunnel_sweep
        sweep.config.misplaced_trigger_delay = 0  # easier test case
        sweep.config.rate_limit_delay = rate_limit_delay
        misplaced = self.sensor_analysis.pellet_misplaced_monitor
        # fake previous engaged:
        sweep.is_engaged = True
        sweep.is_engaged = False
        # then:
        with caplog.at_level(logging.DEBUG):
            misplaced.is_engaged = True
        assert f"delaying tunnel sweep for {rate_limit_delay:.1f}s due to rate" in caplog.text

    @pytest.mark.parametrize("recur_delay_minutes", [15, 60])
    def test_recurrent_engage_outside_ignore_window(self, recur_delay_minutes):
        sweep = self.tunnel_sweep
        tp = sweep.animal_sleep_window = TimePeriod(start=datetime.time(hour=10), stop=datetime.time(hour=18))
        outside_sleep = datetime.datetime.combine(sweep.started_at + timedelta(days=1), tp.stop)
        sweep.config.recurrent_delay_minutes = recur_delay_minutes
        self.increment_perf_now(
            (outside_sleep - sweep.started_at).total_seconds()
        )
        sweep.animal_in_training = True
        assert not sweep.is_engaged
        third_of_recur_delay = 60 * recur_delay_minutes / 3
        self.increment_perf_now(third_of_recur_delay)
        sweep.check_state()
        assert not sweep.is_engaged
        self.increment_perf_now(third_of_recur_delay)
        sweep.check_state()
        assert not sweep.is_engaged, "not yet"
        self.increment_perf_now(third_of_recur_delay + 1)
        sweep.check_state()
        assert sweep.is_engaged, "1st period/trigger of reccurent sweep"

    def test_recurrent_skip_during_ignore_window(self):
        sweep = self.tunnel_sweep
        tp = sweep.animal_sleep_window = TimePeriod(start=datetime.time(hour=10), stop=datetime.time(hour=18))
        inside_sleep = datetime.datetime.combine(sweep.started_at, tp.start)
        self.increment_perf_now(
            (inside_sleep - sweep.started_at).total_seconds()
        )
        sweep.animal_in_training = True
        assert not sweep.is_engaged
        half_d = sweep.config.recurrent_delay_minutes * 60 / 2
        self.increment_perf_now(half_d)
        #
        for _ in range(6):
            sweep.check_state()
            assert not sweep.is_engaged
            self.increment_perf_now(half_d)
        sweep.check_state()
        assert not sweep.is_engaged
