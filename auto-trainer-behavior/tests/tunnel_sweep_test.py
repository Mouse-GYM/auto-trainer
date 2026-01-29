

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

from autotrainer.behavior import CaptureAnalysisResult, IntersessionState
from autotrainer.behavior import SystemState, SystemMachine
from autotrainer.behavior.pellet import PelletState
from autotrainer.behavior.pellet.pellet_machine import PelletMachine
from autotrainer.inference.analysis.intersession_process import IntersessionResponse


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

    @pytest.mark.parametrize("start_session", [False, True])
    def test_it_triggers_with_pellet_misplaced(self, caplog, start_session):
        sweep = self.tunnel_sweep
        misplaced = self.sensor_analysis.pellet_misplaced_monitor
        pellet_dev = self.pellet_dev
        if start_session:
            self.start_session_in_tunnel()
        assert not sweep.is_engaged
        with caplog.at_level(logging.DEBUG):
            misplaced.is_engaged = True
        assert sweep.is_engaged
        assert pellet_dev.set_tunnel_fan_on.call_args_list == [mock.call()]
        pellet_dev.reset_mock()
        misplaced.is_engaged = False
        assert not sweep.is_engaged
        assert pellet_dev.set_tunnel_fan_off.call_args_list == [mock.call()]

    @pytest.mark.parametrize("trigger_delay", [3, 5])
    def test_with_trigger_delay(self, trigger_delay, caplog):
        sweep = self.tunnel_sweep
        sweep.config.misplaced_trigger_delay = trigger_delay
        misplaced = self.sensor_analysis.pellet_misplaced_monitor
        with mock.patch.object(sweep, "_make_new_timer") as m_new_timer:
            misplaced.is_engaged = True
        assert not sweep.is_engaged
        assert m_new_timer.call_args_list == [mock.call(trigger_delay)]
        misplaced.is_engaged = False
        # ensure a new timer is created after:
        with mock.patch.object(sweep, "_make_new_timer") as m_new_timer:
            misplaced.is_engaged = True
        assert m_new_timer.call_args_list == [mock.call(trigger_delay)]

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
