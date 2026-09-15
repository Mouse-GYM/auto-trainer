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

from autotrainer.api import ApiApplicationMode

from tools.acquisition.model.behavior_model import EmergencyControlSource


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
