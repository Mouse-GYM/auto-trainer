import math
import datetime as dtm
from unittest import mock

import pytest

from autotrainer.behavior.pellet import PelletState
from autotrainer.core import PersistenceConfiguration
from tools.acquisition.model.app_model import AppModel

from tools.acquisition.model.app_model_status import AppModelStatus
from top_fixtures import MockSystemMachine


def test_save_config_include_sensor_analysis_monitors_and_detectors(app_model):
    behavior_model = app_model.behavior
    save = behavior_model.save_configuration
    analysis = behavior_model.analysis
    #
    cfg = analysis.global_animal_presence_alarm.config
    cfg.presence_missing_delay_hours += 1
    new = cfg.presence_missing_delay_hours
    assert save().emergency_alarm.global_animal_presence.presence_missing_delay_hours == new
    #
    cfg = analysis.auto_tunnel_sweep_monitor.config
    new = cfg.enabled = not cfg.enabled
    assert save().auto_tunnel_sweep.enabled == new
    #
    thresh = analysis.headbar_pressure_monitor.load_cell_engaged_threshold
    new = analysis.headbar_pressure_monitor.load_cell_engaged_threshold = thresh + 5
    assert save().headbar_pressure.threshold == new
    #
    val = analysis.load_cell_monitor.config.threshold_duration
    new = analysis.load_cell_monitor.config.threshold_duration = val + 3
    assert save().load_cell.threshold_duration == new
    #
    val = analysis.emergency_alarm_monitor.config.external_doors.use
    new = analysis.emergency_alarm_monitor.config.external_doors.use = not val
    assert save().emergency_alarm.external_doors.use == new
    #
    val = analysis.auto_tunnel_sweep_monitor.config.enabled
    new = analysis.auto_tunnel_sweep_monitor.config.enabled = not val
    assert save().auto_tunnel_sweep.enabled == new
    #
    val = analysis.load_cell_tare_monitor.threshold
    new = analysis.load_cell_tare_monitor.threshold = val + 8
    assert save().auto_tare.threshold == new
    #
    val = analysis.audio_thrashing_monitor.config.threshold_percent
    new = analysis.audio_thrashing_monitor.config.threshold_percent = val + 5
    assert save().audio.threshold_percent == new


class TestEmergency(MockSystemMachine):

    @pytest.fixture(autouse=True)
    def _use_app_model(self, app_model):
        self._app_model = app_model
        self._behavior = app_model.behavior

    @pytest.mark.parametrize("baseline_intensity", [0, 5, 100])
    def test_pause_then_resume(self, app_model, baseline_intensity):
        algo = app_model.behavior.algorithm
        self.pellet.state = PelletState.loading
        self.pellet_state_trans.clear()
        algo.baseline_intensity = baseline_intensity
        assert not algo.algo_paused
        tunnel_dev = self.tunnel_dev
        pellet_dev = self.pellet_dev
        tunnel_dev.reset_mock()  # ensure clear
        pellet_dev.reset_mock()  # ensure clear
        #
        assert app_model.behavior.source_emergency is None
        assert self.pellet_state_trans == []
        app_model.behavior.emergency_stop(source="testing")
        assert self.pellet_state_trans == [PelletState.home]
        assert app_model.behavior.source_emergency == "testing"
        assert algo.algo_paused
        assert tunnel_dev.open_tunnel_gate.call_args_list == [mock.call()]
        assert pellet_dev.send_pellet.call_args_list == []
        assert tunnel_dev.update_head_magnet_intensity.call_args_list == [mock.call(0)]
        tunnel_dev.reset_mock()  # ensure clear
        pellet_dev.reset_mock()  # ensure clear
        assert self.pellet_state_trans == [PelletState.home]
        app_model.behavior.emergency_resume(source="testing")
        assert app_model.behavior.source_emergency is None
        assert not algo.algo_paused
        assert tunnel_dev.open_tunnel_gate.call_args_list == [mock.call()]
        assert tunnel_dev.update_head_magnet_intensity.call_args_list == [mock.call(algo.baseline_intensity)]
        self.mock_pellet_ack(until_none=True)
        self.mock_pose_response(pellet_seen=True)
        assert self.pellet_state_trans == [
            PelletState.home,
            PelletState.covering,
            PelletState.retract,
        ]
        # assert pellet_m.send_pellet.call_args_list == [mock.call()]  # is now handled by pellet_machine

    def test_engage_many_times_keeps_last_reason(self, app_model):
        algo = app_model.behavior.algorithm
        assert not algo.algo_paused
        tunnel_dev = self.tunnel_dev
        pellet_dev = self.pellet_dev
        #
        app_model.behavior.emergency_stop(source="testing")
        assert app_model.behavior.source_emergency == "testing"
        tunnel_dev.reset_mock()  # ensure clear
        pellet_dev.reset_mock()  # ensure clear
        #
        app_model.behavior.emergency_stop(source="testing2")
        assert app_model.behavior.source_emergency == "testing2"
        assert tunnel_dev.open_tunnel_gate.call_args_list == []
        assert pellet_dev.send_pellet.call_args_list == []
        assert tunnel_dev.update_head_magnet_intensity.call_args_list == []

    def test_user_source_cannot_be_resumed(self, app_model):
        algo = app_model.behavior.algorithm
        assert not algo.algo_paused
        tunnel_dev = self.tunnel_dev
        pellet_dev = self.pellet_dev
        app_model.behavior.emergency_stop(source="user-button")
        assert app_model.behavior.source_emergency == "user-button"
        assert algo.algo_paused
        tunnel_dev.reset_mock()  # ensure clear
        pellet_dev.reset_mock()  # ensure clear
        # now:
        app_model.behavior.emergency_resume(source="something-else")
        # but still engaged:
        assert algo.algo_paused
        assert app_model.behavior.source_emergency == "user-button"
        assert tunnel_dev.open_tunnel_gate.call_args_list == []
        assert pellet_dev.send_pellet.call_args_list == []
        assert tunnel_dev.update_head_magnet_intensity.call_args_list == []
        # now:
        app_model.behavior.emergency_resume(source="user-button")
        assert not algo.algo_paused


mid_day = dtm.datetime(2026,1,1, 12, 0)
mid_night = dtm.datetime(2026, 1, 1, 0, 0)


class TestColorLed:

    @pytest.fixture()
    def app_model(self, app_model) -> AppModel:
        self._app_model = app_model
        app_model.status = AppModelStatus.ACQUIRING  # force
        fault_alarm = self.fault_alarm = app_model.analysis.system_fault_alarm
        # ensure used as emergency condition:
        fault_alarm.config.use = True
        fault_alarm.config.is_emergency_condition = True
        self.ignore_window = app_model.behavior.algorithm.active_config.animal_sleep_window
        alarm_mon = app_model.analysis.emergency_alarm_monitor
        # force not use daemon, so that below set of is_engaged are all handled in this thread.
        alarm_mon.use_daemon = False
        alarm_mon.restart()
        return app_model

    @property
    def get_color(self):
        return self._app_model.behavior.get_led_color

    def test_start_stop_same_day(self, app_model):
        get_color = self.get_color
        fault_alarm = self.fault_alarm
        #
        assert get_color(now=mid_day) == (0, 0, 0)
        assert get_color(now=mid_night) == (0, 100, 0)
        #
        app_model.analysis.free_disk_space_detector.config.min_limit_mb = math.inf
        app_model.analysis.free_disk_space_detector.set_persistence_config(
            PersistenceConfiguration(output_location="/"))
        assert get_color(now=mid_day) == (100, 0, 0)
        assert get_color(now=mid_night) == (100, 0, 0)
        #
        fault_alarm.config.is_emergency_condition = False
        fault_alarm.property_changed(fault_alarm.CONFIG, fault_alarm.config, None)
        assert get_color(now=mid_day) == (0, 0, 0)
        assert get_color(now=mid_night) == (100, 100, 0)

    def test_start_stop_not_same_day(self, app_model: AppModel):
        get_color = self.get_color
        fault_alarm = self.fault_alarm
        #
        self.ignore_window.start = dtm.time(22, 0)
        self.ignore_window.stop = dtm.time(10, 0)
        #
        assert get_color(now=mid_night) == (0, 0, 0)
        assert get_color(now=mid_day) == (0, 100, 0)
        #
        app_model.analysis.free_disk_space_detector.config.min_limit_mb = math.inf
        app_model.analysis.free_disk_space_detector.set_persistence_config(
            PersistenceConfiguration(output_location="/"))
        assert get_color(now=mid_day) == (100, 0, 0)
        assert get_color(now=mid_night) == (100, 0, 0)
        #
        fault_alarm.config.is_emergency_condition = False
        fault_alarm.property_changed(fault_alarm.CONFIG, fault_alarm.config, None)
        assert get_color(now=mid_night) == (0, 0, 0)
        assert get_color(now=mid_day) == (100, 100, 0)
