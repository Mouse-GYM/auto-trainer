import contextlib
import logging
from pathlib import Path
from threading import Timer
from unittest import mock

import pytest

from autotrainer.core import get_perf_now
from autotrainer.core.video_detection import PresenceDetectionAttrs

from autotrainer.behavior import SystemMachine, SystemState

from top_fixtures import MockSystemMachine


class TestAutoCloseGate(MockSystemMachine):

    def start_trial_in_tunnel(self):  # noqa
        self.mock_pose_response(pellet_seen=True)
        super().start_trial_in_tunnel(set_recording_status=True)

    def _init(self, machine: SystemMachine):
        super()._init(machine)
        algo = self.algo
        algo.intertrial_enabled = True
        cfg = algo.auto_close_gate_on_intertrial_config
        cfg.enabled = True
        cfg.trial_min_duration = 0
        cfg.delay_after_cage_enter = 0
        algo.top_camera_presence_detection = PresenceDetectionAttrs()

    @pytest.mark.parametrize("enabled", [False, True])
    @pytest.mark.parametrize("sess_min_duration", [0, 300])
    @pytest.mark.parametrize("sess_duration", [15, 450])
    def test_auto_close_gate(self, machine, enabled, caplog, sess_duration, sess_min_duration, monkeypatch):
        """with "common" conditions"""
        algo = machine.algorithm
        auto_close_gate_cfg = algo.auto_close_gate_on_intertrial_config
        auto_close_gate_cfg.enabled = enabled
        if enabled:
            algo._topcam_presence = topcam = PresenceDetectionAttrs()
            topcam.last_presence_start_perf_c = get_perf_now()
        else:
            topcam = None
        auto_close_gate_cfg.trial_min_duration = sess_min_duration

        orig = machine._consider_close_gate_during_intertrial
        def before_consider_close_gate(*args, **kwargs):
            if topcam is not None:
                topcam.last_presence_start_perf_c = self.get_current_perf_now()
            return orig(*args, **kwargs)
        monkeypatch.setattr(machine, "_consider_close_gate_during_intertrial", before_consider_close_gate)

        self.mock_pose_response(pellet_seen=True)
        self.start_trial_in_tunnel()
        assert algo.is_in_trial_capture
        algo.update_mouse_seen(True)

        caplog.set_level(logging.DEBUG)
        with self.mock_analysis():
            self.increment_perf_now(sess_duration)
            self.exit_tunnel()

        assert not algo.is_in_trial_capture
        if enabled and sess_duration >= sess_min_duration:
            assert "Closing tunnel gate for intertrial" in caplog.text
            assert self.tunnel_dev.close_tunnel_gate.call_args_list == [mock.call()]
        else:
            assert "Closing tunnel gate for intertrial" not in caplog.text
            assert self.tunnel_dev.close_tunnel_gate.call_args_list == []
            if enabled:
                assert "trial duration too short, skipping auto-close-gate" in caplog.text

    def test_when_algo_paused_before_consider(self, machine, monkeypatch, caplog):
        algo = self.algo
        orig = machine._consider_close_gate_during_intertrial
        def before_consider_close_gate(*args, **kwargs):
            algo.algo_paused = True
            return orig(*args, **kwargs)
        monkeypatch.setattr(machine, "_consider_close_gate_during_intertrial", before_consider_close_gate)
        self.start_trial_in_tunnel()
        algo.update_mouse_seen(True)
        caplog.set_level(logging.DEBUG)
        with self.mock_analysis():
            self.exit_tunnel()
        assert "algo disabled, skipping auto-close-gate" in caplog.text

    @pytest.mark.parametrize("delay", [1, 5])
    def test_with_delay_after_cage_enter(self, machine, caplog, delay):
        algo = self.algo
        cfg = algo.auto_close_gate_on_intertrial_config
        cfg.delay_after_cage_enter = delay
        self.start_trial_in_tunnel()
        algo.update_mouse_seen(True)
        caplog.set_level(logging.DEBUG)
        half = delay // 2
        m_timer2 = None
        def consider_again():
            assert m_timer.call_args_list == [mock.call(0.1, machine._consider_close_gate_during_intertrial)]
            assert m_timer.return_value.cancel.call_args_list == []  # not yet
            self.increment_perf_now(half)
            nonlocal m_timer2
            with self.patch_timer(f"{machine.__class__.__module__}._consider_close_gate_timer") as m_timer2:
                machine._consider_close_gate_during_intertrial()
            assert m_timer.return_value.cancel.call_args_list == [mock.call()]  # ensure prev timer is canceled

        with self.mock_analysis(det_conc_func=consider_again):
            with self.patch_timer(f"{machine.__class__.__module__}._consider_close_gate_timer") as m_timer:
                self.exit_tunnel()
        assert m_timer2.call_args_list == [mock.call(0.1, machine._consider_close_gate_during_intertrial)]
        assert m_timer2.return_value.cancel.call_args_list == [mock.call()]  # given finished intersession

    def test_when_not_anymore_intertrial(self, machine, monkeypatch, caplog):
        algo = self.algo
        cfg = algo.auto_close_gate_on_intertrial_config
        cfg.delay_after_cage_enter = 1
        self.start_trial_in_tunnel()
        algo.update_mouse_seen(True)
        caplog.set_level(logging.DEBUG)
        with self.mock_analysis():
            with self.patch_timer(f"{machine.__class__.__module__}._consider_close_gate_timer") as m_timer:
                self.exit_tunnel()
        assert m_timer.call_args_list == [mock.call(0.1, machine._consider_close_gate_during_intertrial)]
        machine._consider_close_gate_during_intertrial()
        assert "not anymore intertrial, skipping auto-close-gate" in caplog.text

    def test_without_topcam(self, machine, caplog):
        algo = self.algo
        algo.top_camera_presence_detection = None
        self.start_trial_in_tunnel()
        algo.update_mouse_seen(True)
        caplog.set_level(logging.WARNING)
        with self.mock_analysis():
            self.exit_tunnel()
        assert "topcam presence not enabled, forced skipping auto-close-gate" in caplog.text
