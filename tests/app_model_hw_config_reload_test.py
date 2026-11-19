import contextlib
import shutil
import threading
import time
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Tuple
from unittest import mock

import pytest

from autotrainer.core.testing import increase_simulate_perf_now
from autotrainer.device import CompoundMovements, MotorConfigurationFile
from tools.acquisition.model.app_model import AppModel, InvalidTargetAppModelStatus
from tools.acquisition.model.app_model_status import AppModelStatus
from tools.acquisition.model.behavior_model import EmergencyControlSource

_TESTS_DIR = Path(__file__).parent
_MALFORMED_YAML = "tunnel: [unclosed\n"


@contextlib.contextmanager
def advancing_perf_now() -> Iterator[None]:
    # a stop with connected hardware waits on simulated time, which only moves when something advances it
    is_done = threading.Event()

    def advance():
        while not is_done.is_set():
            increase_simulate_perf_now(0.5)
            time.sleep(0.01)

    thread = threading.Thread(target=advance, daemon=True)
    thread.start()
    try:
        yield
    finally:
        is_done.set()
        thread.join()


@pytest.fixture
def errors(app_model) -> List[Tuple[str, str]]:
    collected: List[Tuple[str, str]] = []

    def collect(title: str, content: str):
        collected.append((title, content))

    app_model.on_error += collect
    return collected


@pytest.fixture
def running(app_model):
    assert app_model.capture_start(target_status=AppModelStatus.ACQUIRING) is True
    yield app_model
    # a test may leave a simulated Stop behind, which would make capture_stop return without stopping
    app_model._stop_requested.clear()
    app_model._acquisition_stopping = False
    with advancing_perf_now():
        app_model.capture_stop()


def wrap_after(monkeypatch, obj, name: str, after: Callable[[], None]) -> mock.MagicMock:
    orig = getattr(obj, name)

    def call(*args, **kwargs):
        result = orig(*args, **kwargs)
        after()
        return result

    spy = mock.MagicMock(side_effect=call)
    monkeypatch.setattr(obj, name, spy)
    return spy


def spy_on(monkeypatch, obj, name: str) -> mock.MagicMock:
    spy = mock.MagicMock(wraps=getattr(obj, name))
    monkeypatch.setattr(obj, name, spy)
    return spy


def collect_can_reload_events(app_model) -> List[bool]:
    values: List[bool] = []

    def on_changed(name, value, _prev):
        if name == AppModel.Props.CAN_RELOAD_HW_CONFIG:
            values.append(value)

    app_model.property_changed += on_changed
    return values


def point_at(monkeypatch, cls, path: Path):
    monkeypatch.setattr(cls, "DEFAULT_LOCATION", path)


def assert_canceled_quietly(callback: mock.MagicMock, errors: List[Tuple[str, str]]):
    assert errors == []
    callback.assert_called_once()
    assert callback.call_args.args == (False,)
    assert "canceled" in callback.call_args.kwargs["error"]


# Idle and loader cases

def test_idle_reload_replaces_both_configs(app_model, monkeypatch, errors):
    assert app_model.load_configuration() is True
    before_motors, before_move = app_model._motors_config, app_model._move_config
    stop_spy = spy_on(monkeypatch, app_model, "capture_stop")
    callback = mock.MagicMock()

    app_model.reload_motor_and_move_config(callback=callback)

    callback.assert_called_once_with(True)
    assert errors == []
    assert app_model._motors_config is not None and app_model._motors_config is not before_motors
    assert app_model._move_config is not None and app_model._move_config is not before_move
    assert stop_spy.call_count == 0
    assert not app_model._stop_requested.is_set()
    assert app_model.can_reload_hw_config is True
    assert app_model.hw_config_reload_in_progress is False


def test_idle_reload_clears_a_startup_load_error_so_start_is_accepted(app_model, monkeypatch, tmp_path, errors):
    motors_path = tmp_path / "motor_config.yaml"
    motors_path.write_text(_MALFORMED_YAML)
    point_at(monkeypatch, MotorConfigurationFile, motors_path)
    assert app_model.load_configuration() is False
    assert app_model._motors_load_error is not None
    assert app_model.capture_start(target_status=AppModelStatus.ACQUIRING) is False

    shutil.copyfile(_TESTS_DIR / "motor_config.yaml", motors_path)
    errors.clear()
    callback = mock.MagicMock()
    app_model.reload_motor_and_move_config(callback=callback)

    callback.assert_called_once_with(True)
    assert errors == []
    assert app_model.config_errors == []
    assert app_model.capture_start(target_status=AppModelStatus.ACQUIRING) is True
    with advancing_perf_now():
        app_model.capture_stop()


def test_second_load_configuration_clears_a_fixed_load_error(app_model, monkeypatch, tmp_path):
    motors_path = tmp_path / "motor_config.yaml"
    motors_path.write_text(_MALFORMED_YAML)
    point_at(monkeypatch, MotorConfigurationFile, motors_path)
    assert app_model.load_configuration() is False
    assert app_model._motors_load_error is not None

    shutil.copyfile(_TESTS_DIR / "motor_config.yaml", motors_path)
    assert app_model.load_configuration() is True
    assert app_model._motors_load_error is None
    assert app_model.config_errors == []


def test_startup_falls_back_to_defaults_for_a_missing_file(app_model, monkeypatch, tmp_path):
    point_at(monkeypatch, MotorConfigurationFile, tmp_path / "missing_motor_config.yaml")
    assert app_model.load_configuration() is True
    assert app_model._motors_load_error is None
    assert app_model._motors_config is not None


def test_reload_refuses_a_missing_file_and_changes_nothing(app_model, monkeypatch, tmp_path, errors):
    assert app_model.load_configuration() is True
    before_motors, before_move = app_model._motors_config, app_model._move_config
    missing_path = tmp_path / "missing_move_config.yaml"
    point_at(monkeypatch, CompoundMovements, missing_path)
    callback = mock.MagicMock()

    app_model.reload_motor_and_move_config(callback=callback)

    assert len(errors) == 1
    assert missing_path.name in errors[0][1]
    assert callback.call_args.args == (False,)
    assert app_model._motors_config is before_motors
    assert app_model._move_config is before_move
    assert app_model._move_load_error is None
    assert app_model.hw_config_reload_in_progress is False
    assert app_model.can_reload_hw_config is True


def test_failed_reload_keeps_the_previous_load_error(app_model, monkeypatch, tmp_path, errors):
    motors_path = tmp_path / "motor_config.yaml"
    motors_path.write_text(_MALFORMED_YAML)
    point_at(monkeypatch, MotorConfigurationFile, motors_path)
    assert app_model.load_configuration() is False
    previous_error = app_model._motors_load_error
    assert previous_error is not None
    callback = mock.MagicMock()

    app_model.reload_motor_and_move_config(callback=callback)

    assert callback.call_args.args == (False,)
    assert app_model._motors_load_error == previous_error
    assert app_model._motors_config is None


def test_reload_during_a_start_is_refused_without_stopping(app_model, monkeypatch, errors):
    stop_spy = spy_on(monkeypatch, app_model, "capture_stop")
    callback = mock.MagicMock()
    app_model._acquisition_starting = True
    try:
        app_model.reload_motor_and_move_config(callback=callback)
    finally:
        app_model._acquisition_starting = False

    assert len(errors) == 1
    assert "can only be reloaded while Idle or Running" in errors[0][1]
    assert callback.call_args.args == (False,)
    assert stop_spy.call_count == 0
    assert app_model._motors_config is None
    assert app_model._move_config is None


@pytest.mark.parametrize("state", ["idle", "start_in_progress"])
def test_a_no_op_stop_leaves_no_stop_request_behind(app_model, errors, state):
    events = collect_can_reload_events(app_model)
    if state == "start_in_progress":
        app_model._acquisition_starting = True
    try:
        app_model.capture_stop()
    finally:
        app_model._acquisition_starting = False

    assert not app_model._stop_requested.is_set()
    if state == "idle":
        assert events == []
        assert app_model.can_reload_hw_config is True

    callback = mock.MagicMock()
    app_model.reload_motor_and_move_config(callback=callback)
    callback.assert_called_once_with(True)
    assert app_model._motors_config is not None
    assert app_model._move_config is not None


# Running cases

def test_running_reload_pushes_and_homes(running, monkeypatch, errors):
    app_model = running
    hard = app_model.hardware
    dev_conn = hard.device_connection
    motors_spy = spy_on(monkeypatch, dev_conn, "use_motor_configurations")
    move_spy = spy_on(monkeypatch, dev_conn, "use_compound_movements")
    home_spy = spy_on(monkeypatch, hard, "send_home")
    stop_spy = spy_on(monkeypatch, app_model, "capture_stop")
    callback = mock.MagicMock()

    app_model.reload_motor_and_move_config(callback=callback)

    callback.assert_called_once_with(True)
    assert errors == []
    assert motors_spy.call_count == 1
    assert motors_spy.call_args.args[0] is app_model._motors_config
    assert move_spy.call_count == 1
    assert move_spy.call_args.args[0] is app_model._move_config
    assert home_spy.call_count == 1
    assert stop_spy.call_count == 0
    assert app_model.status is AppModelStatus.ACQUIRING


def test_reload_during_an_emergency_is_refused_without_stopping(running, monkeypatch, errors):
    app_model = running
    app_model.behavior.emergency_stop(source=EmergencyControlSource.USER_BUTTON)
    hard = app_model.hardware
    motors_spy = spy_on(monkeypatch, hard.device_connection, "use_motor_configurations")
    home_spy = spy_on(monkeypatch, hard, "send_home")
    stop_spy = spy_on(monkeypatch, app_model, "capture_stop")
    errors.clear()
    callback = mock.MagicMock()

    app_model.reload_motor_and_move_config(callback=callback)

    assert len(errors) == 1
    assert "emergency" in errors[0][1]
    assert callback.call_args.args == (False,)
    assert motors_spy.call_count == 0
    assert home_spy.call_count == 0
    assert stop_spy.call_count == 0
    assert app_model.status is AppModelStatus.ACQUIRING
    assert app_model.acquisition_started is True


@pytest.mark.parametrize("mode", [AppModelStatus.ANIMAL_IN_DEVICE, AppModelStatus.CALIBRATION_DCS])
def test_reload_in_another_mode_is_refused_without_stopping(running, monkeypatch, errors, mode):
    app_model = running
    app_model.status = mode
    motors_spy = spy_on(monkeypatch, app_model.hardware.device_connection, "use_motor_configurations")
    stop_spy = spy_on(monkeypatch, app_model, "capture_stop")
    callback = mock.MagicMock()

    app_model.reload_motor_and_move_config(callback=callback)

    assert len(errors) == 1
    assert callback.call_args.args == (False,)
    assert motors_spy.call_count == 0
    assert stop_spy.call_count == 0
    assert app_model.status is mode


@pytest.mark.parametrize("flag", ["_stop_requested", "_acquisition_stopping"])
def test_a_stop_already_underway_cancels_quietly(running, monkeypatch, errors, flag):
    app_model = running
    before_motors, before_move = app_model._motors_config, app_model._move_config
    motors_spy = spy_on(monkeypatch, app_model.hardware.device_connection, "use_motor_configurations")
    stop_spy = spy_on(monkeypatch, app_model, "capture_stop")
    callback = mock.MagicMock()
    if flag == "_stop_requested":
        app_model._stop_requested.set()
    else:
        app_model._acquisition_stopping = True
    try:
        app_model.reload_motor_and_move_config(callback=callback)
    finally:
        app_model._stop_requested.clear()
        app_model._acquisition_stopping = False

    assert_canceled_quietly(callback, errors)
    assert motors_spy.call_count == 0
    assert stop_spy.call_count == 0
    assert app_model._motors_config is before_motors
    assert app_model._move_config is before_move


@pytest.mark.parametrize("step", ["use_motor_configurations", "use_compound_movements"])
def test_a_stop_during_the_push_cancels_quietly(running, monkeypatch, errors, step):
    app_model = running
    hard = app_model.hardware
    dev_conn = hard.device_connection
    wrap_after(monkeypatch, dev_conn, step, app_model._stop_requested.set)
    procedures_spy = spy_on(monkeypatch, dev_conn, "set_steps_procedure")
    home_spy = spy_on(monkeypatch, hard, "send_home")
    stop_spy = spy_on(monkeypatch, app_model, "capture_stop")
    callback = mock.MagicMock()

    app_model.reload_motor_and_move_config(callback=callback)

    assert_canceled_quietly(callback, errors)
    assert home_spy.call_count == 0
    assert stop_spy.call_count == 0
    assert app_model.status is AppModelStatus.ACQUIRING
    if step == "use_motor_configurations":
        assert procedures_spy.call_count == 0


def test_a_push_failure_after_the_first_write_stops_acquisition(running, monkeypatch, errors):
    app_model = running
    dev_conn = app_model.hardware.device_connection
    monkeypatch.setattr(dev_conn, "use_compound_movements", mock.MagicMock(side_effect=RuntimeError("simulated")))
    stop_spy = spy_on(monkeypatch, app_model, "capture_stop")
    callback = mock.MagicMock()

    with advancing_perf_now():
        app_model.reload_motor_and_move_config(callback=callback)

    assert len(errors) == 1
    assert "partial configuration" in errors[0][1]
    assert callback.call_args.args == (False,)
    assert stop_spy.call_count == 1
    assert app_model.status is AppModelStatus.IDLE
    assert app_model.acquisition_started is False
    assert app_model.can_reload_hw_config is True


def test_an_abort_before_the_first_write_does_not_stop(running, monkeypatch, errors):
    app_model = running
    dev_conn = app_model.hardware.device_connection
    failing = mock.MagicMock(side_effect=RuntimeError("simulated failure before any write"))
    monkeypatch.setattr(dev_conn, "use_motor_configurations", failing)
    stop_spy = spy_on(monkeypatch, app_model, "capture_stop")
    callback = mock.MagicMock()

    app_model.reload_motor_and_move_config(callback=callback)

    assert len(errors) == 1
    assert "Nothing was written" in errors[0][1]
    assert callback.call_args.args == (False,)
    assert stop_spy.call_count == 0
    assert app_model.status is AppModelStatus.ACQUIRING


def test_animal_transitions_are_refused_during_a_reload(running, monkeypatch, errors):
    app_model = running
    targets = (AppModelStatus.ANIMAL_IN_DEVICE, AppModelStatus.ANIMAL_IN_TRAINING, AppModelStatus.CALIBRATION_DCS)
    seen: Dict[str, object] = {}

    def during_push():
        seen["valid"] = [app_model.is_target_status_valid(target) for target in targets]
        try:
            app_model.status = AppModelStatus.ANIMAL_IN_DEVICE
            seen["refused"] = False
        except InvalidTargetAppModelStatus:
            seen["refused"] = True
        seen["can_reload"] = app_model.can_reload_hw_config
        seen["in_progress"] = app_model.hw_config_reload_in_progress

    wrap_after(monkeypatch, app_model.hardware.device_connection, "use_motor_configurations", during_push)
    callback = mock.MagicMock()

    app_model.reload_motor_and_move_config(callback=callback)

    assert seen == {"valid": [False, False, False], "refused": True, "can_reload": False, "in_progress": True}
    callback.assert_called_once_with(True)
    assert errors == []
    assert app_model.status is AppModelStatus.ACQUIRING
    assert app_model.is_target_status_valid(AppModelStatus.ANIMAL_IN_DEVICE) is True
    assert app_model.is_target_status_valid(AppModelStatus.CALIBRATION_DCS) is True


def test_a_second_reload_is_refused_while_one_is_in_progress(running, monkeypatch, errors):
    app_model = running
    nested_callback = mock.MagicMock()
    wrap_after(monkeypatch, app_model.hardware.device_connection, "use_motor_configurations",
               lambda: app_model.reload_motor_and_move_config(callback=nested_callback))
    callback = mock.MagicMock()

    app_model.reload_motor_and_move_config(callback=callback)

    assert nested_callback.call_args.args == (False,)
    assert len(errors) == 1
    assert "already in progress" in errors[0][1]
    callback.assert_called_once_with(True)


# "Can reload" state

def test_can_reload_follows_start_stop_and_mode(app_model, monkeypatch):
    events = collect_can_reload_events(app_model)
    during: Dict[str, bool] = {}
    hard = app_model.hardware
    orig_connect = hard.connect
    orig_capture_stop_impl = app_model._capture_stop

    def connect(*args, **kwargs):
        during["start"] = app_model.can_reload_hw_config
        return orig_connect(*args, **kwargs)

    def capture_stop_impl(*args, **kwargs):
        during["stop"] = app_model.can_reload_hw_config
        return orig_capture_stop_impl(*args, **kwargs)

    monkeypatch.setattr(hard, "connect", connect)
    monkeypatch.setattr(app_model, "_capture_stop", capture_stop_impl)

    assert app_model.can_reload_hw_config is True
    assert app_model.capture_start(target_status=AppModelStatus.ACQUIRING) is True
    assert app_model.can_reload_hw_config is True
    app_model.status = AppModelStatus.ANIMAL_IN_DEVICE
    assert app_model.can_reload_hw_config is False
    app_model.status = AppModelStatus.ACQUIRING
    assert app_model.can_reload_hw_config is True
    with advancing_perf_now():
        app_model.capture_stop()
    assert app_model.can_reload_hw_config is True

    assert during == {"start": False, "stop": False}
    assert events == [False, True, False, True, False, True]


def test_can_reload_turns_off_while_a_stop_waits_for_the_lock(running):
    app_model = running
    events = collect_can_reload_events(app_model)
    stopper = threading.Thread(target=app_model.capture_stop, name="test-stopper", daemon=True)
    with app_model.app_lock:
        stopper.start()
        deadline = time.monotonic() + 5
        while not (app_model._stop_requested.is_set() and events) and time.monotonic() < deadline:
            time.sleep(0.001)
        waiting_can_reload = app_model.can_reload_hw_config
        waiting_events = list(events)
    with advancing_perf_now():
        stopper.join(timeout=30)

    assert waiting_can_reload is False
    assert waiting_events == [False]
    assert not stopper.is_alive()
    assert app_model.status is AppModelStatus.IDLE
    assert app_model.can_reload_hw_config is True
