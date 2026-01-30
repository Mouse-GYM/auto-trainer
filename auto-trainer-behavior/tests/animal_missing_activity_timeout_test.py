
import contextlib
import logging
import math
import time
from itertools import chain
from pathlib import Path
from threading import Timer
from typing import ContextManager, Union
from unittest import mock

import pytest

from autotrainer.core.multiproc import DaemonTimer
from top_fixtures import MockSystemMachine

from autotrainer.behavior import CaptureAnalysisResult, IntersessionState, RecordingEndingReason
from autotrainer.behavior import SystemState, SystemMachine
from autotrainer.behavior.pellet import PelletState
from autotrainer.behavior.pellet.pellet_machine import PelletMachine
from autotrainer.inference.analysis.intersession_process import IntersessionResponse


# for small diff of timers delay:
class AlmostEqualFloat(float):
    def __eq__(self, other):
        return abs(self - other) < 0.001


class TestConsiderAutoEndSession(MockSystemMachine):

    capture_end_reason = None
    capture_end_count = 0

    def capture_ended(self, reason: RecordingEndingReason):
        self.capture_end_reason = reason
        self.capture_end_count += 1

    def _init(self, machine: SystemMachine):
        super()._init(machine)
        self.algo.session_capture_ending += self.capture_ended

    def patch_timer(self):  # noqa
        return super().patch_timer("autotrainer.behavior.system_machine._consider_auto_end_session_timer")

    @pytest.mark.parametrize("timeout_delay_minutes", [1, 3])
    def test_it_triggers(self, machine, timeout_delay_minutes):
        algo = self.algo
        algo.active_config.auto_end_session.no_activity_delay_minutes = timeout_delay_minutes
        with self.patch_timer() as m_timer:
            self.start_session_in_tunnel()

        delay_seconds = AlmostEqualFloat(timeout_delay_minutes * 60)
        assert m_timer.call_args_list == [
            mock.call(delay_seconds, machine._consider_auto_end_session)
        ]
        half_delay = delay_seconds // 2
        self.increment_perf_now(half_delay)
        with self.patch_timer() as m_timer_2:
            machine._consider_auto_end_session()
        assert algo.is_in_session
        assert m_timer_2.call_args_list == [
            mock.call(AlmostEqualFloat(half_delay), machine._consider_auto_end_session)
        ]
        assert m_timer.return_value.cancel.call_args_list == [mock.call()]
        self.increment_perf_now(half_delay + 1)
        with self.patch_timer() as m_timer_3:
            machine._consider_auto_end_session()
        assert m_timer_3.call_args_list == []
        assert m_timer_2.return_value.cancel.call_args_list == 2 * [mock.call()]
        # NB: canceled 2 times, once by _consider_auto_end_session and once by end_session itself.
        assert self.capture_end_count == 1
        assert self.capture_end_reason == RecordingEndingReason.MISSING_ANIMAL_ACTIVITY_TIMEOUT
        assert self.tunnel_dev.tare_load_cell.call_args_list == [mock.call()]

    @pytest.mark.parametrize("timeout_delay_minutes", [1, 5])
    def test_mouse_seen_delay_the_trigger(self, machine, timeout_delay_minutes):
        algo = self.algo
        timeout_delay = timeout_delay_minutes * 60
        algo.active_config.auto_end_session.no_activity_delay_minutes = timeout_delay_minutes
        with self.patch_timer() as m_timer:
            self.start_session_in_tunnel()
        self.increment_perf_now(timeout_delay // 2)
        algo.update_mouse_seen(True)
        with self.patch_timer() as m_timer_2:
            machine._consider_auto_end_session()
        assert m_timer_2.call_args_list == [
            mock.call(AlmostEqualFloat(timeout_delay), machine._consider_auto_end_session)
        ]
        assert m_timer.return_value.cancel.call_args_list == [mock.call()]

    def test_its_canceled_on_end_session(self, machine):
        with self.patch_timer() as m_timer:
            self.start_session_in_tunnel()
        assert m_timer.return_value.cancel.call_args_list == []
        self.exit_tunnel()
        assert m_timer.return_value.cancel.call_args_list == [mock.call()]
