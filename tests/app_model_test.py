import logging
import random
import threading
import time
from unittest import mock


import pytest

from autotrainer.behavior.behavior_algorithm import BehaviorAlgoStatus
from autotrainer.device import EmulationInterface
from autotrainer.device.device_interface import Acknowledge
from tools.acquisition.model.app_model import app_status_to_api_app_mode, app_status_to_behavior_algo_status
from tools.acquisition.model.app_model_status import AppModelStatus

from autotrainer.api import ApiApplicationMode, ApiSystemStatus

from tools.acquisition.model.behavior_model import EmergencyControlSource


BEHAVIOR_SETTING_SOURCES = [
    ("is_pellet_delivery_enabled",
     lambda app, value: setattr(app.behavior.algorithm, "pellet_delivery_enabled", value)),
    ("is_pellet_cover_enabled",
     lambda app, value: setattr(app.behavior.algorithm, "pellet_cover_enabled", value)),
    ("is_intertrial_pellet_shift_enabled",
     lambda app, value: setattr(app.behavior.algorithm, "intertrial_pellet_shift_enabled", value)),
    ("is_triangle_pellet_distance_detection_enabled",
     lambda app, value: setattr(app.behavior.algorithm, "use_triangle_pellet_distance_too_far", value)),
    ("is_auto_close_gate_on_intertrial_enabled",
     lambda app, value: setattr(app.behavior.algorithm.auto_close_gate_on_intertrial_config, "enabled", value)),
    ("is_auto_clamp_enabled",
     lambda app, value: setattr(app.behavior.algorithm, "head_fixation_enabled", value)),
    ("is_batch_trials_enabled",
     lambda app, value: setattr(app.behavior.algorithm.batch_trial_recording_config, "enabled", value)),
]

PELLET_SETTING_SOURCES = [
    ("is_home_on_excessive_drift_enabled",
     lambda app, value: setattr(app.behavior.algorithm.home_on_excessive_drift_distance_config, "enabled", value)),
    ("is_tunnel_sweep_enabled",
     lambda app, value: setattr(app.analysis.auto_tunnel_sweep_monitor.config, "enabled", value)),
]


def _setting_ids(sources):
    return [entry[0] for entry in sources]



class TestStatus:

    @pytest.mark.parametrize("app_model_status", list(AppModelStatus))
    def test_it_can_translate_to_api_app_mode(self, app_model_status: AppModelStatus) -> None:
        api_app_mode = app_status_to_api_app_mode(app_model_status)
        assert isinstance(api_app_mode, ApiApplicationMode)

    @pytest.mark.parametrize("app_model_status", list(AppModelStatus))
    def test_it_can_translate_to_behavior_status(self, app_model_status: AppModelStatus):
        algo_status = app_status_to_behavior_algo_status(app_model_status)
        if app_model_status in {AppModelStatus.CALIBRATION_3D, AppModelStatus.CALIBRATION_DCS}:
            assert algo_status is None
        else:
            assert isinstance(algo_status, BehaviorAlgoStatus)
            assert algo_status.name == app_model_status.name



class TestSystemStatusPayload:

    def test_it_builds_a_system_status_payload(self, app_model):
        status = app_model._make_api_system_status_payload()
        assert isinstance(status, ApiSystemStatus)

    @pytest.mark.parametrize("is_open", [True, False])
    def test_it_reports_the_tunnel_gate_state(self, app_model, is_open):
        # read-only property; its only public write path is an inbound CAN property-change message.
        app_model.hardware._tunnel_gate_open_status = is_open
        status = app_model._make_api_system_status_payload()
        assert status.tunnel_device.is_gate_open is is_open

    @pytest.mark.parametrize("field_name,set_source", BEHAVIOR_SETTING_SOURCES,
                             ids=_setting_ids(BEHAVIOR_SETTING_SOURCES))
    @pytest.mark.parametrize("value", [True, False])
    def test_it_reports_each_behavior_setting(self, app_model, field_name, set_source, value):
        set_source(app_model, value)
        status = app_model._make_api_system_status_payload()
        assert getattr(status.behavior, field_name) is value

    @pytest.mark.parametrize("value", [True, False])
    def test_it_reports_live_analysis_enabled(self, app_model, monkeypatch, value):
        # is_enabled is a read-only property on InferenceProtocol; a plain bool on the class shadows it.
        monkeypatch.setattr(type(app_model.inference), "is_enabled", value)
        status = app_model._make_api_system_status_payload()
        assert status.behavior.is_live_analysis_enabled is value

    @pytest.mark.parametrize("field_name,set_source", PELLET_SETTING_SOURCES,
                             ids=_setting_ids(PELLET_SETTING_SOURCES))
    @pytest.mark.parametrize("value", [True, False])
    def test_it_reports_each_pellet_device_setting(self, app_model, field_name, set_source, value):
        set_source(app_model, value)
        status = app_model._make_api_system_status_payload()
        assert getattr(status.pellet_device, field_name) is value


def test_it_drain_record_stop_sema_on_session_recording_start(app_model):
    app_model._record_stop_sema.release()
    app_model._record_stop_sema.release()
    app_model.behavior.algorithm.start_trial_capture(reason="manual")
    assert app_model._record_stop_sema.acquire(block=False) is False, "cannot acquire after: it should be back to 0"


def test_resume_fails_if_hard_reconnect_fails(
    app_model,
    monkeypatch,
    mock_get_perf_now,
    caplog,
):
    app_model.capture_start(target_status=AppModelStatus.ACQUIRING)
    algo = app_model.behavior.algorithm
    hard = app_model.hardware
    analysis = app_model.analysis
    can_dev = hard.can_device
    dev_conn = hard.device_connection
    iface = can_dev.device_interface
    assert isinstance(iface, EmulationInterface)
    emergency_mon = analysis.emergency_alarm_monitor
    # analysis
    # put some randomness:
    uuid_nack_errno = random.getrandbits(32)
    if uuid_nack_errno == 0:
        uuid_nack_errno = -42
    def bad_delay(delay_sec):
        iface._messages.append(Acknowledge(uuid=iface.next_uuid(), error=uuid_nack_errno))
        return True
    monkeypatch.setattr(iface, iface.delay.__name__, bad_delay)
    with pytest.raises(RuntimeError, match=rf"uuid_nacks=\[{uuid_nack_errno}\]"):
        tokens = set()
        with dev_conn.await_acknowledge(tokens):
            tokens.add(hard.delay(1))
    p_end = time.perf_counter() + 0.5
    while time.perf_counter() < p_end:
        time.sleep(0.001)  # give some time processing for background threads, notably emergency monitor
        if algo.algo_paused:
            break
    assert algo.algo_paused
    assert emergency_mon.is_engaged
    assert analysis.device_comm_alarm.is_engaged
    # now try resume, for that we need keep increase simulate perf now
    stop_increase = threading.Event()
    def increase_perf_now():
        # NB: give some time for background threads to process the probe from emergency_resume,
        # and/but
        while not stop_increase.is_set():
            mock_get_perf_now.increase_simulate_perf_now(0.1)
            time.sleep(0.05)
    th = threading.Thread(target=increase_perf_now, daemon=True)
    th.start()
    orig_connect = hard.connect
    fail_conn = mock.MagicMock(side_effect=RuntimeError("faked failed connect"))
    monkeypatch.setattr(hard, hard.connect.__name__, fail_conn)
    try:
        app_model.behavior.emergency_resume(source=EmergencyControlSource.USER_BUTTON)
    finally:
        stop_increase.set()
        th.join()
    assert fail_conn.call_count >= 1
    assert algo.algo_paused  # still
    assert emergency_mon.is_engaged
    assert "before_emergency_resumed failed, skipping emergency_resume" in caplog.text
    # now:
    hard.connect = orig_connect
    app_model.behavior.emergency_resume(source=EmergencyControlSource.USER_BUTTON)
    assert not algo.algo_paused  # not anymore
    assert not emergency_mon.is_engaged
    assert emergency_mon.engaged_reasons == []
