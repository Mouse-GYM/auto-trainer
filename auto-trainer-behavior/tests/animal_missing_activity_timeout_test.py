import logging
import math
from unittest import mock

import pytest

from top_fixtures import MockSystemMachine, AlmostEqualFloat

from autotrainer.behavior import IntertrialState
from autotrainer.core.interfaces import CaptureAnalysisResult, RecordingEndingReason
from autotrainer.behavior import SystemState, SystemMachine


class BaseAutoEndSession(MockSystemMachine):

    capture_end_reason = None
    capture_end_count = 0

    def capture_ended(self, reason: RecordingEndingReason):
        self.capture_end_reason = reason
        self.capture_end_count += 1

    def _init(self, machine: SystemMachine):
        super()._init(machine)
        self.algo.trial_capture_ending += self.capture_ended

    def patch_timer(self):  # noqa
        return super().patch_timer("autotrainer.behavior.system_machine._consider_auto_end_trial_timer")

    def test_its_canceled_on_end_trial(self, machine):
        self.mock_pose_response(pellet_seen=True)
        with self.patch_timer() as m_timer:
            self.start_trial_in_tunnel(set_recording_status=True)
        assert m_timer.return_value.cancel.call_args_list == []
        self.exit_tunnel()
        assert not self.algo.is_in_trial_capture
        assert m_timer.return_value.cancel.call_args_list == [mock.call()]


class TestWithMissingNoseActivity(BaseAutoEndSession):

    def _init(self, machine: SystemMachine):
        super()._init(machine)
        self.algo.active_config.auto_end_trial.animal_tunnel_no_activity_delay = 0  # disable this one

    @pytest.mark.parametrize("timeout_delay_minutes", [1, 3])
    def test_it_triggers(self, machine, timeout_delay_minutes):
        algo = self.algo
        algo.active_config.auto_end_trial.no_activity_delay_minutes = timeout_delay_minutes
        self.mock_pose_response(pellet_seen=True)
        with self.patch_timer() as m_timer:
            self.start_trial_in_tunnel(set_recording_status=True)

        delay_seconds = AlmostEqualFloat(timeout_delay_minutes * 60)
        assert m_timer.call_args_list == [
            mock.call(delay_seconds, machine._consider_auto_end_trial_capture)
        ]
        half_delay = delay_seconds // 2
        self.increment_perf_now(half_delay)
        with self.patch_timer() as m_timer_2:
            machine._consider_auto_end_trial_capture()
        assert algo.is_in_trial_capture
        assert m_timer_2.call_args_list == [
            mock.call(AlmostEqualFloat(half_delay), machine._consider_auto_end_trial_capture)
        ]
        assert m_timer.return_value.cancel.call_args_list == [mock.call()]
        assert self.capture_end_count == 0
        assert algo.is_in_trial_capture
        self.increment_perf_now(half_delay + 1)
        with self.patch_timer() as m_timer_3:
            machine._consider_auto_end_trial_capture()
        assert not algo.is_in_trial_capture
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
        algo.active_config.auto_end_trial.no_activity_delay_minutes = timeout_delay_minutes
        self.mock_pose_response(pellet_seen=True)
        with self.patch_timer() as m_timer:
            self.start_trial_in_tunnel(set_recording_status=True)
        self.increment_perf_now(timeout_delay // 2)
        algo.update_mouse_seen(True)
        with self.patch_timer() as m_timer_2:
            machine._consider_auto_end_trial_capture()
        assert algo.is_in_trial_capture
        assert m_timer_2.call_args_list == [
            mock.call(AlmostEqualFloat(timeout_delay), machine._consider_auto_end_trial_capture)
        ]
        assert m_timer.return_value.cancel.call_args_list == [mock.call()]


class TestWithAnimalTunnelMissingActivity(BaseAutoEndSession):

    def _init(self, machine: SystemMachine):
        super()._init(machine)
        cfg = self.algo.active_config.auto_end_trial
        cfg.animal_tunnel_no_activity_delay = 30
        cfg.no_activity_delay_minutes = 0  # disable this one

    def test_it_triggers_normally(self, machine):
        algo = self.algo
        cfg = algo.active_config.auto_end_trial
        self.mock_pose_response(pellet_seen=True)
        with self.patch_timer() as m_timer:
            self.start_trial_in_tunnel(set_recording_status=True)
        delay = AlmostEqualFloat(cfg.animal_tunnel_no_activity_delay)
        assert m_timer.call_args_list == [
            mock.call(delay, machine._consider_auto_end_trial_capture)
        ]
        # also ensure it updates correctly if re-called halfway to delay:
        self.increment_perf_now(delay / 2)
        with self.patch_timer() as m_timer2:
            machine._consider_auto_end_trial_capture()
        assert m_timer2.call_args_list == [
            mock.call(AlmostEqualFloat(delay / 2), machine._consider_auto_end_trial_capture)
        ]
        assert m_timer.return_value.cancel.call_args_list == [mock.call()], "previous timer must have been cancelled"

    def test_it_triggers_with_inf_tunnel_missing_activity_but_then_disable(self, machine, caplog):
        algo = self.algo
        cfg = algo.active_config.auto_end_trial
        cfg.animal_tunnel_no_activity_delay = math.inf
        algo.update_pellet_seen(True)
        with self.patch_timer() as m_timer:
            self.start_trial_in_tunnel(set_recording_status=True)
        assert m_timer.call_args_list == []
        assert "Stopping consider auto_end_trial given all conditions disabled" in caplog.text

    def test_without_low_variance(self, machine, caplog):
        self.sensor_analysis.load_cell_tare_monitor.context.low_variance_engaged = False
        algo = self.algo
        cfg = algo.active_config.auto_end_trial
        algo.update_pellet_seen(True)
        with self.patch_timer() as m_timer:
            self.start_trial_in_tunnel(set_recording_status=True)
        delay = cfg.animal_tunnel_no_activity_delay
        assert m_timer.call_args_list == [
            mock.call(delay, machine._consider_auto_end_trial_capture)
        ]

    def test_if_called_when_no_intertrial_is_skipped(self, machine, caplog):
        with caplog.at_level(logging.DEBUG):
            machine._consider_auto_end_trial_capture()
        assert "skipping consider_auto_end_trial given not in capture" in caplog.text
