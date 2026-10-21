import contextlib
import threading
import time
from functools import partial
from typing import Any, Callable, Iterator, List, Optional
from unittest import mock

import pytest

from autotrainer.api import (
    ApiAnimalStatus,
    ApiApplicationMode,
    ApiCommand,
    ApiCommandRequest,
    ApiCommandRequestErrorKind,
    ApiCommandRequestResponse,
    ApiCommandRequestResult,
    ApiEmergencyResumeReason,
    ApiEventKind,
    ApiTrainingMode,
    RpcService,
)
from autotrainer.behavior import TrainingMode
from autotrainer.core.testing import increase_simulate_perf_now

import tools.acquisition.model.app_model as app_model_module
from tools.acquisition.model.app_model_status import AppModelStatus
from tools.acquisition.model.behavior_model import EmergencyControlSource


@pytest.fixture(autouse=True)
def _use_mock_event_manager(mock_event_manager):
    pass


class _InlineThread(threading.Thread):

    def __init__(self, group=None, target=None, daemon=None, name=None):
        super().__init__(group, target=target, daemon=daemon, name=name)
        self._orig_target = target
        self._started = False
        self._stopped = False

    def start(self):
        if self._started:
            raise RuntimeError("already started")
        self._started = True
        self._orig_target()
        self._stopped = True

    def join(self, *, timeout=None):
        if not self._started:
            raise RuntimeError("not started")
        if not self._stopped:
            raise RuntimeError("still running")

    def is_alive(self):
        return self._started and not self._stopped


class _DeferredThread(_InlineThread):

    def __init__(self, *args, target=None, workers: List[Callable[[], None]], **kwargs):
        super().__init__(*args, **kwargs)
        self._orig_target = target
        self._workers = workers

    def start(self):
        self._started = True
        self._workers.append(self.run)

    def run(self):
        self._orig_target()
        self._stopped = True


class _FailingThread(_InlineThread):

    def start(self):
        raise RuntimeError("can't start new thread")


@pytest.fixture
def rpc_service(app_model, monkeypatch) -> mock.MagicMock:
    monkeypatch.setattr(app_model_module, "_make_rpc_command_thread", _InlineThread)
    service = mock.MagicMock(spec=RpcService)
    app_model.rpc_service = service
    return service


def _send(app_model, command: ApiCommand, data: Any = None) -> ApiCommandRequestResponse:
    return app_model._handle_rpc_service_command(ApiCommandRequest(command=command, nonce=7, data=data))


def _final_result(rpc_service: mock.MagicMock) -> ApiCommandRequestResponse:
    assert rpc_service.send_command_result.call_count == 1
    return rpc_service.send_command_result.call_args.args[0]


def _event_contexts(mock_event_manager, kind: ApiEventKind) -> List[Any]:
    return [call.args[0].context for call in mock_event_manager.post_event.call_args_list
            if call.args[0].kind == kind]


@contextlib.contextmanager
def _advancing_perf_now() -> Iterator[None]:
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


SETTINGS = [
    (ApiCommand.SET_LIVE_ANALYSIS_ENABLED, "behavior", "is_live_analysis_enabled"),
    (ApiCommand.SET_PELLET_DELIVERY_ENABLED, "behavior", "is_pellet_delivery_enabled"),
    (ApiCommand.SET_PELLET_COVER_ENABLED, "behavior", "is_pellet_cover_enabled"),
    (ApiCommand.SET_INTERTRIAL_PELLET_SHIFT_ENABLED, "behavior", "is_intertrial_pellet_shift_enabled"),
    (ApiCommand.SET_HOME_ON_EXCESSIVE_DRIFT_ENABLED, "pellet_device", "is_home_on_excessive_drift_enabled"),
    (ApiCommand.SET_TRIANGLE_PELLET_DISTANCE_DETECTION_ENABLED, "behavior",
     "is_triangle_pellet_distance_detection_enabled"),
    (ApiCommand.SET_AUTO_CLOSE_GATE_ON_INTERTRIAL_ENABLED, "behavior", "is_auto_close_gate_on_intertrial_enabled"),
    (ApiCommand.SET_AUTO_CLAMP_ENABLED, "behavior", "is_auto_clamp_enabled"),
    (ApiCommand.SET_TUNNEL_SWEEP_ENABLED, "pellet_device", "is_tunnel_sweep_enabled"),
    (ApiCommand.SET_BATCH_TRIALS_ENABLED, "behavior", "is_batch_trials_enabled"),
]
SETTING_COMMANDS = [command for command, _, _ in SETTINGS]
OBSOLETE_COMMANDS = [ApiCommand.START_ACQUISITION, ApiCommand.STOP_ACQUISITION]


def _status_field(app_model, section: str, field: str) -> bool:
    return getattr(getattr(app_model._make_api_system_status_payload(), section), field)


class TestDispatch:

    @pytest.mark.parametrize("command", [command for command in ApiCommand if command not in OBSOLETE_COMMANDS])
    def test_every_command_is_recognized(self, app_model, rpc_service, command):
        response = _send(app_model, command)
        assert response.result != ApiCommandRequestResult.UNRECOGNIZED

    @pytest.mark.parametrize("command", OBSOLETE_COMMANDS)
    def test_obsolete_commands_are_unrecognized(self, app_model, monkeypatch, command):
        capture_start = mock.MagicMock(return_value=True)
        capture_stop = mock.MagicMock()
        monkeypatch.setattr(app_model, "capture_start", capture_start)
        monkeypatch.setattr(app_model, "capture_stop", capture_stop)
        response = _send(app_model, command)
        assert response.result == ApiCommandRequestResult.UNRECOGNIZED
        assert "obsolete" in response.error_message
        assert capture_start.call_count == 0
        assert capture_stop.call_count == 0
        assert app_model.status == AppModelStatus.IDLE

    def test_the_settings_table_covers_commands_1000_to_1099(self):
        assert set(app_model_module._RPC_BEHAVIOR_SETTINGS) == {
            command for command in ApiCommand if 1000 <= command < 1100}


class TestAsyncHelper:

    @staticmethod
    def _request() -> ApiCommandRequest:
        return ApiCommandRequest(command=ApiCommand.NONE, nonce=11)

    def test_a_payload_is_success(self, app_model, rpc_service):
        reply = app_model._handle_rpc_async_command(self._request(), lambda: {"key": 1})
        assert reply == ApiCommandRequestResult.PENDING_WITH_NOTIFICATION
        result = _final_result(rpc_service)
        assert result.result == ApiCommandRequestResult.SUCCESS
        assert result.data == {"key": 1}
        assert result.command == ApiCommand.NONE
        assert result.nonce == 11

    def test_false_is_failed(self, app_model, rpc_service):
        app_model._handle_rpc_async_command(self._request(), lambda: False)
        result = _final_result(rpc_service)
        assert result.result == ApiCommandRequestResult.FAILED
        assert result.error_code == ApiCommandRequestErrorKind.COMMAND_ERROR
        assert result.data is None

    def test_an_exception_is_exception(self, app_model, rpc_service):
        def fail():
            raise RuntimeError("worker broke")

        app_model._handle_rpc_async_command(self._request(), fail)
        result = _final_result(rpc_service)
        assert result.result == ApiCommandRequestResult.EXCEPTION
        assert result.error_code == ApiCommandRequestErrorKind.SYSTEM_ERROR
        assert "worker broke" in result.error_message

    def test_nothing_is_sent_without_a_service(self, app_model, rpc_service):
        app_model.rpc_service = None
        reply = app_model._handle_rpc_async_command(self._request(), lambda: True)
        assert reply == ApiCommandRequestResult.PENDING_WITH_NOTIFICATION
        assert rpc_service.send_command_result.call_count == 0


class TestBehaviorSettings:

    @pytest.fixture(autouse=True)
    def _settable_live_analysis(self, app_model, monkeypatch):
        # is_enabled is a read-only property on InferenceProtocol; a plain bool on the class shadows it
        monkeypatch.setattr(type(app_model.inference), "is_enabled", False)

    @pytest.mark.parametrize("value", [True, False])
    @pytest.mark.parametrize("command,section,field", SETTINGS, ids=[command.name for command in SETTING_COMMANDS])
    def test_it_sets_the_setting(self, app_model, monkeypatch, command, section, field, value):
        monitor = app_model.analysis.auto_tunnel_sweep_monitor
        monkeypatch.setattr(monitor, "restart", mock.MagicMock())
        monkeypatch.setattr(monitor, "stop", mock.MagicMock())
        for sent in (not value, value):
            response = _send(app_model, command, {"enabled": sent})
            assert response.result == ApiCommandRequestResult.SUCCESS
            assert response.data == {"enabled": sent}
        assert _status_field(app_model, section, field) is value

    @pytest.mark.parametrize("command", SETTING_COMMANDS, ids=[command.name for command in SETTING_COMMANDS])
    def test_it_succeeds_when_already_set(self, app_model, monkeypatch, command):
        monitor = app_model.analysis.auto_tunnel_sweep_monitor
        monkeypatch.setattr(monitor, "restart", mock.MagicMock())
        monkeypatch.setattr(monitor, "stop", mock.MagicMock())
        first = _send(app_model, command, {"enabled": True})
        second = _send(app_model, command, {"enabled": True})
        assert first.result == second.result == ApiCommandRequestResult.SUCCESS
        assert second.data == {"enabled": True}

    @pytest.mark.parametrize("payload", [
        None, {}, {"enabled": None}, {"enabled": 1}, {"enabled": 0}, {"enabled": "true"}, ["enabled"],
    ])
    def test_it_rejects_a_payload_that_is_not_a_boolean(self, app_model, payload):
        algo = app_model.behavior.algorithm
        before = algo.pellet_delivery_enabled
        response = _send(app_model, ApiCommand.SET_PELLET_DELIVERY_ENABLED, payload)
        assert response.result == ApiCommandRequestResult.FAILED
        assert response.data is None
        assert response.error_code == ApiCommandRequestErrorKind.COMMAND_ERROR
        assert algo.pellet_delivery_enabled == before

    @pytest.mark.parametrize("command", SETTING_COMMANDS, ids=[command.name for command in SETTING_COMMANDS])
    def test_every_setting_rejects_a_missing_payload(self, app_model, command):
        assert _send(app_model, command).result == ApiCommandRequestResult.FAILED

    def test_a_dependent_setting_changes_while_its_gate_is_off(self, app_model):
        algo = app_model.behavior.algorithm
        algo.pellet_delivery_enabled = False
        algo.pellet_cover_enabled = False
        assert not app_model.inference.is_enabled
        response = _send(app_model, ApiCommand.SET_PELLET_COVER_ENABLED, {"enabled": True})
        assert response.result == ApiCommandRequestResult.SUCCESS
        assert algo.pellet_cover_enabled is True

    @pytest.mark.parametrize("command", [
        command for command in SETTING_COMMANDS
        if command not in (ApiCommand.SET_AUTO_CLAMP_ENABLED, ApiCommand.SET_TUNNEL_SWEEP_ENABLED)
    ])
    def test_it_publishes_no_event(self, app_model, mock_event_manager, command):
        current = _send(app_model, command, {"enabled": True}).data["enabled"]
        before = mock_event_manager.post_event.call_count
        response = _send(app_model, command, {"enabled": not current})
        assert response.data == {"enabled": not current}
        assert mock_event_manager.post_event.call_count == before

    def test_auto_clamp_publishes_only_on_change(self, app_model, mock_event_manager):
        algo = app_model.behavior.algorithm
        _send(app_model, ApiCommand.SET_AUTO_CLAMP_ENABLED, {"enabled": False})
        mock_event_manager.post_event.reset_mock()
        _send(app_model, ApiCommand.SET_AUTO_CLAMP_ENABLED, {"enabled": True})
        assert _event_contexts(mock_event_manager, ApiEventKind.autoClampEnabledChanged) == [{"is_enabled": True}]
        assert algo.active_config.head_clamp.enabled is True
        _send(app_model, ApiCommand.SET_AUTO_CLAMP_ENABLED, {"enabled": True})
        assert len(_event_contexts(mock_event_manager, ApiEventKind.autoClampEnabledChanged)) == 1

    def test_tunnel_sweep_starts_and_stops_the_monitor(self, app_model, monkeypatch):
        monitor = app_model.analysis.auto_tunnel_sweep_monitor
        restart = mock.MagicMock()
        stop = mock.MagicMock()
        monkeypatch.setattr(monitor, "restart", restart)
        monkeypatch.setattr(monitor, "stop", stop)
        monitor.config.enabled = False
        _send(app_model, ApiCommand.SET_TUNNEL_SWEEP_ENABLED, {"enabled": True})
        assert (restart.call_count, stop.call_count) == (1, 0)
        _send(app_model, ApiCommand.SET_TUNNEL_SWEEP_ENABLED, {"enabled": True})
        assert (restart.call_count, stop.call_count) == (1, 0)
        _send(app_model, ApiCommand.SET_TUNNEL_SWEEP_ENABLED, {"enabled": False})
        assert (restart.call_count, stop.call_count) == (1, 1)


class TestGetAnimals:

    def test_no_animals_is_an_empty_list(self, app_model):
        response = _send(app_model, ApiCommand.GET_ANIMALS)
        assert response.result == ApiCommandRequestResult.SUCCESS
        assert response.data == []

    def test_it_lists_every_animal(self, app_model, mock_event_manager):
        app_model.add_animal("mouse-b")
        app_model.add_animal("mouse-a")
        mock_event_manager.post_event.reset_mock()
        response = _send(app_model, ApiCommand.GET_ANIMALS)
        assert response.result == ApiCommandRequestResult.SUCCESS
        assert all(isinstance(item, ApiAnimalStatus) for item in response.data)
        assert {item.name for item in response.data} == {"mouse-a", "mouse-b"}
        assert mock_event_manager.post_event.call_count == 0

    def test_a_query_during_an_add_sees_a_whole_list(self, app_model):
        app_model.add_animal("mouse-a")
        before = app_model.animals
        replies: List[ApiCommandRequestResponse] = []

        def getter(model):
            return model.__dict__["_animals"]

        def setter(model, value):
            model.__dict__["_animals"] = value
            replies.append(_send(model, ApiCommand.GET_ANIMALS))

        # a property on the class takes precedence over the instance attribute, so every write to _animals is probed;
        # the patch must be gone before the fixture's teardown sets every attribute to None
        with mock.patch.object(app_model_module.AppModel, "_animals", property(getter, setter), create=True):
            app_model.add_animal("mouse-b")
        assert replies
        for reply in replies:
            assert reply.result == ApiCommandRequestResult.SUCCESS
            assert {item.name for item in reply.data} == {"mouse-a", "mouse-b"}
        assert [animal.name for animal in before] == ["mouse-a"]


class TestTrainingMode:

    def test_it_sets_the_training_mode(self, app_model, mock_event_manager):
        response = _send(app_model, ApiCommand.SET_TRAINING_MODE, {"mode": int(ApiTrainingMode.AUTOMATIC)})
        assert response.result == ApiCommandRequestResult.PENDING_WITH_NOTIFICATION
        app_model.join_rpc_threads()
        # assert response.result == ApiCommandRequestResult.SUCCESS
        # assert response.data == {"mode": ApiTrainingMode.AUTOMATIC}
        assert app_model.training_mode == TrainingMode.AUTOMATIC
        contexts = _event_contexts(mock_event_manager, ApiEventKind.trainingModeChanged)
        assert contexts == [{"training_mode": ApiTrainingMode.AUTOMATIC}]
        assert type(contexts[0]["training_mode"]) is ApiTrainingMode

    def test_the_current_mode_succeeds_without_an_event(self, app_model, mock_event_manager):
        assert app_model.training_mode is TrainingMode.MANUAL
        response = _send(app_model, ApiCommand.SET_TRAINING_MODE, {"mode": int(ApiTrainingMode.MANUAL)})
        assert response.result == ApiCommandRequestResult.SUCCESS
        assert _event_contexts(mock_event_manager, ApiEventKind.trainingModeChanged) == []

    def test_undefined_is_unavailable(self, app_model):
        response = _send(app_model, ApiCommand.SET_TRAINING_MODE, {"mode": int(ApiTrainingMode.UNDEFINED)})
        assert response.result == ApiCommandRequestResult.UNAVAILABLE
        assert response.data is None
        assert app_model.training_mode is TrainingMode.MANUAL

    @pytest.mark.parametrize("payload", [None, {}, {"mode": "AUTOMATIC"}, {"mode": True}, {"mode": 300.0}, {"mode": 42}])
    def test_it_rejects_an_invalid_mode(self, app_model, payload):
        response = _send(app_model, ApiCommand.SET_TRAINING_MODE, payload)
        assert response.result == ApiCommandRequestResult.FAILED
        assert response.data is None

    @pytest.mark.parametrize("statuses", [
        [AppModelStatus.ANIMAL_IN_TRAINING],
        [AppModelStatus.CALIBRATION_3D],
        [AppModelStatus.ACQUIRING, AppModelStatus.CALIBRATION_DCS],
    ], ids=["ANIMAL_IN_TRAINING", "CALIBRATION_3D", "CALIBRATION_DCS"])
    def test_it_is_unavailable_while_locked(self, app_model, statuses):
        app_model.behavior.algorithm.reload_diamond_triangle_config()
        for status in statuses:
            app_model.status = status
        response = _send(app_model, ApiCommand.SET_TRAINING_MODE, {"mode": int(ApiTrainingMode.AUTOMATIC)})
        assert response.result == ApiCommandRequestResult.UNAVAILABLE
        assert app_model.training_mode is TrainingMode.MANUAL

    def test_the_setter_publishes_an_api_training_mode(self, app_model, mock_event_manager):
        app_model.training_mode = TrainingMode.AUTOMATIC
        assert _event_contexts(mock_event_manager, ApiEventKind.trainingModeChanged) == [
            {"training_mode": ApiTrainingMode.AUTOMATIC}]


class TestApplicationModeEvent:

    def test_a_status_change_posts_one_event(self, app_model, mock_event_manager):
        app_model.status = AppModelStatus.CALIBRATION_3D
        assert _event_contexts(mock_event_manager, ApiEventKind.applicationModeChanged) == [
            {"mode": ApiApplicationMode.CALIBRATION_3D}]
        app_model.status = AppModelStatus.CALIBRATION_3D
        app_model.status = AppModelStatus.IDLE
        assert _event_contexts(mock_event_manager, ApiEventKind.applicationModeChanged) == [
            {"mode": ApiApplicationMode.CALIBRATION_3D}, {"mode": ApiApplicationMode.IDLE}]

    def test_a_forced_stop_while_idle_posts_nothing(self, app_model, mock_event_manager):
        with _advancing_perf_now():
            app_model.capture_stop(force=True)
        assert _event_contexts(mock_event_manager, ApiEventKind.applicationModeChanged) == []


def _mode(mode: ApiApplicationMode) -> dict:
    return {"mode": int(mode)}


class TestSetApplicationMode:

    @pytest.fixture
    def capture_stubs(self, app_model, monkeypatch) -> mock.MagicMock:
        stubs = mock.MagicMock()
        stubs.capture_start.return_value = False
        monkeypatch.setattr(app_model, "capture_start", stubs.capture_start)
        monkeypatch.setattr(app_model, "capture_stop", stubs.capture_stop)
        return stubs

    @pytest.mark.parametrize("payload", [None, {}, {"mode": "RUNNING"}, {"mode": True}, {"mode": 100.0},
                                         {"mode": 12345}, [100]])
    def test_it_rejects_an_invalid_mode(self, app_model, rpc_service, payload):
        response = _send(app_model, ApiCommand.SET_APPLICATION_MODE, payload)
        assert response.result == ApiCommandRequestResult.FAILED
        assert response.data is None

    @pytest.mark.parametrize("mode", [ApiApplicationMode.CALIBRATION_DCS, ApiApplicationMode.CALIBRATION_3D])
    def test_calibration_modes_are_unavailable(self, app_model, rpc_service, mode):
        response = _send(app_model, ApiCommand.SET_APPLICATION_MODE, _mode(mode))
        assert response.result == ApiCommandRequestResult.UNAVAILABLE
        assert app_model.status == AppModelStatus.IDLE

    def test_the_current_mode_succeeds_without_an_event(self, app_model, rpc_service, capture_stubs,
                                                         mock_event_manager):
        before = mock_event_manager.post_event.call_count
        response = _send(app_model, ApiCommand.SET_APPLICATION_MODE, _mode(ApiApplicationMode.IDLE))
        assert response.result == ApiCommandRequestResult.SUCCESS
        assert response.data == {"mode": ApiApplicationMode.IDLE}
        assert mock_event_manager.post_event.call_count == before
        assert capture_stubs.capture_stop.call_count == 0

    def test_it_is_unavailable_during_a_calibration(self, app_model, rpc_service, capture_stubs):
        app_model.status = AppModelStatus.CALIBRATION_3D
        for mode in (ApiApplicationMode.RUNNING, ApiApplicationMode.IDLE):
            response = _send(app_model, ApiCommand.SET_APPLICATION_MODE, _mode(mode))
            assert response.result == ApiCommandRequestResult.UNAVAILABLE

    @pytest.mark.parametrize("mode", [ApiApplicationMode.IDLE, ApiApplicationMode.RUNNING])
    @pytest.mark.parametrize("flag", ["_acquisition_starting", "_acquisition_stopping"])
    def test_it_is_unavailable_during_a_start_or_stop(self, app_model, rpc_service, capture_stubs,
                                                      mock_event_manager, monkeypatch, flag, mode):
        # the flag is still set during the fixture's teardown, which is harmless: with _acquisition_started False,
        # the capture_stop in on_close returns before it reads the flags
        monkeypatch.setattr(app_model, flag, True)
        response = _send(app_model, ApiCommand.SET_APPLICATION_MODE, _mode(mode))
        assert response.result == ApiCommandRequestResult.UNAVAILABLE
        assert response.data is None
        assert capture_stubs.capture_start.call_count == 0
        assert capture_stubs.capture_stop.call_count == 0
        assert _event_contexts(mock_event_manager, ApiEventKind.applicationModeChanged) == []

    @pytest.mark.parametrize("mode", [ApiApplicationMode.IDLE, ApiApplicationMode.RUNNING,
                                      ApiApplicationMode.IN_DEVICE])
    def test_a_second_request_waits_for_the_first_worker(self, app_model, rpc_service, capture_stubs,
                                                         monkeypatch, mode):
        workers: List[Callable[[], None]] = []
        monkeypatch.setattr(app_model_module, "_make_rpc_command_thread", partial(_DeferredThread, workers=workers))
        first = _send(app_model, ApiCommand.SET_APPLICATION_MODE, _mode(ApiApplicationMode.RUNNING))
        assert first.result == ApiCommandRequestResult.PENDING_WITH_NOTIFICATION
        assert len(workers) == 1
        assert capture_stubs.capture_start.call_count == 0

        second = _send(app_model, ApiCommand.SET_APPLICATION_MODE, _mode(mode))
        assert second.result == ApiCommandRequestResult.UNAVAILABLE
        assert second.data is None
        assert len(workers) == 1

        workers[0]()
        assert capture_stubs.capture_start.call_count == 1
        assert _final_result(rpc_service).result == ApiCommandRequestResult.FAILED

        after = _send(app_model, ApiCommand.SET_APPLICATION_MODE, _mode(ApiApplicationMode.IDLE))
        assert after.result == ApiCommandRequestResult.SUCCESS
        assert after.data == {"mode": ApiApplicationMode.IDLE}

    def test_a_launch_failure_releases_the_reservation(self, app_model, rpc_service, capture_stubs, monkeypatch):
        monkeypatch.setattr(app_model_module, "_make_rpc_command_thread", _FailingThread)
        response = _send(app_model, ApiCommand.SET_APPLICATION_MODE, _mode(ApiApplicationMode.RUNNING))
        assert response.result == ApiCommandRequestResult.EXCEPTION
        monkeypatch.setattr(app_model_module, "_make_rpc_command_thread", _InlineThread)
        response = _send(app_model, ApiCommand.SET_APPLICATION_MODE, _mode(ApiApplicationMode.RUNNING))
        assert response.result == ApiCommandRequestResult.PENDING_WITH_NOTIFICATION

    def test_it_is_unavailable_without_a_valid_dcs(self, app_model, rpc_service, capture_stubs):
        app_model.behavior.algorithm.diamond_triangle_config = None
        response = _send(app_model, ApiCommand.SET_APPLICATION_MODE, _mode(ApiApplicationMode.IN_TRAINING))
        assert response.result == ApiCommandRequestResult.UNAVAILABLE
        assert "DCS" in response.error_message
        assert capture_stubs.capture_start.call_count == 0

    def test_a_failed_start_is_failed_with_its_cause(self, app_model, rpc_service, monkeypatch):
        def failing_start(**kwargs):
            app_model.on_error("Camera start failed", "left camera did not start")
            return False

        monkeypatch.setattr(app_model, "capture_start", failing_start)
        response = _send(app_model, ApiCommand.SET_APPLICATION_MODE, _mode(ApiApplicationMode.RUNNING))
        assert response.result == ApiCommandRequestResult.PENDING_WITH_NOTIFICATION
        result = _final_result(rpc_service)
        assert result.result == ApiCommandRequestResult.FAILED
        assert result.data is None
        assert result.error_code == ApiCommandRequestErrorKind.COMMAND_ERROR
        assert "left camera did not start" in result.error_message

    def test_a_start_that_raises_is_an_exception(self, app_model, rpc_service, monkeypatch):
        monkeypatch.setattr(app_model, "capture_start", mock.MagicMock(side_effect=RuntimeError("no cameras")))
        _send(app_model, ApiCommand.SET_APPLICATION_MODE, _mode(ApiApplicationMode.RUNNING))
        result = _final_result(rpc_service)
        assert result.result == ApiCommandRequestResult.EXCEPTION
        assert result.error_code == ApiCommandRequestErrorKind.SYSTEM_ERROR

    def test_the_start_is_cancelled_when_the_app_closes(self, app_model, rpc_service, monkeypatch):
        captured: List[Callable[[], bool]] = []

        def capture_start(*, target_status, is_cancelled):
            captured.append(is_cancelled)
            return False

        monkeypatch.setattr(app_model, "capture_start", capture_start)
        _send(app_model, ApiCommand.SET_APPLICATION_MODE, _mode(ApiApplicationMode.RUNNING))
        is_cancelled = captured[0]
        assert is_cancelled() is False
        with mock.patch.object(app_model, "_closing", True):
            # nb: need it restored to False/previous value when test ends,
            # so that app_model on_close will be executed by the fixture providing it.
            assert is_cancelled() is True

    def test_it_moves_through_the_running_modes(self, app_model, rpc_service, mock_event_manager):
        response = _send(app_model, ApiCommand.SET_APPLICATION_MODE, _mode(ApiApplicationMode.RUNNING))
        assert response.result == ApiCommandRequestResult.PENDING_WITH_NOTIFICATION
        result = _final_result(rpc_service)
        assert result.result == ApiCommandRequestResult.SUCCESS
        assert result.data == {"mode": ApiApplicationMode.RUNNING}
        assert result.nonce == 7

        for mode in (ApiApplicationMode.IN_DEVICE, ApiApplicationMode.IN_TRAINING):
            response = _send(app_model, ApiCommand.SET_APPLICATION_MODE, _mode(mode))
            assert response.result == ApiCommandRequestResult.SUCCESS
            assert response.data == {"mode": mode}

        rpc_service.send_command_result.reset_mock()
        with _advancing_perf_now():
            response = _send(app_model, ApiCommand.SET_APPLICATION_MODE, _mode(ApiApplicationMode.IDLE))
        assert response.result == ApiCommandRequestResult.PENDING_WITH_NOTIFICATION
        result = _final_result(rpc_service)
        assert result.result == ApiCommandRequestResult.SUCCESS
        assert result.data == {"mode": ApiApplicationMode.IDLE}

        assert _event_contexts(mock_event_manager, ApiEventKind.applicationModeChanged) == [
            {"mode": ApiApplicationMode.RUNNING},
            {"mode": ApiApplicationMode.IN_DEVICE},
            {"mode": ApiApplicationMode.IN_TRAINING},
            {"mode": ApiApplicationMode.IDLE},
        ]


class TestEmergencyResume:

    def test_it_fails_at_once_when_not_stopped(self, app_model, rpc_service, mock_event_manager):
        response = _send(app_model, ApiCommand.EMERGENCY_RESUME)
        assert response.result == ApiCommandRequestResult.FAILED
        assert response.data is None
        assert rpc_service.send_command_result.call_count == 0
        assert _event_contexts(mock_event_manager, ApiEventKind.emergencyResume) == []

    def test_it_resumes_asynchronously(self, app_model, rpc_service, mock_event_manager):
        app_model.behavior.emergency_stop(source="testing")
        response = _send(app_model, ApiCommand.EMERGENCY_RESUME)
        assert response.result == ApiCommandRequestResult.PENDING_WITH_NOTIFICATION
        result = _final_result(rpc_service)
        assert result.result == ApiCommandRequestResult.SUCCESS
        assert result.data == {"reason": EmergencyControlSource.RPC_SERVICE}
        assert not app_model.behavior.algorithm.algo_paused
        contexts = _event_contexts(mock_event_manager, ApiEventKind.emergencyResume)
        assert len(contexts) == 1
        assert contexts[0]["reason"] == EmergencyControlSource.RPC_SERVICE
        assert contexts[0]["reason_code"] == ApiEmergencyResumeReason.rpc_service

    def test_it_fails_when_the_resume_fails(self, app_model, rpc_service, mock_event_manager):
        def probe_failed():
            raise RuntimeError("probe failed")

        behavior = app_model.behavior
        behavior.emergency_stop(source="testing")
        behavior.before_emergency_resumed += probe_failed
        try:
            _send(app_model, ApiCommand.EMERGENCY_RESUME)
        finally:
            behavior.before_emergency_resumed -= probe_failed
        result = _final_result(rpc_service)
        assert result.result == ApiCommandRequestResult.FAILED
        assert result.data is None
        assert "probe failed" in result.error_message
        assert behavior.algorithm.algo_paused
        assert _event_contexts(mock_event_manager, ApiEventKind.emergencyResume) == []

    def test_it_succeeds_when_stopped_again_right_after_resuming(self, app_model, rpc_service):
        behavior = app_model.behavior

        def stop_again(source: Optional[str] = None):
            behavior.emergency_stop(source="again")

        behavior.emergency_stop(source="testing")
        behavior.emergency_resumed += stop_again
        try:
            _send(app_model, ApiCommand.EMERGENCY_RESUME)
        finally:
            behavior.emergency_resumed -= stop_again
        assert _final_result(rpc_service).result == ApiCommandRequestResult.SUCCESS
        assert behavior.algorithm.algo_paused is True

    def test_emergency_stop_is_unchanged(self, app_model, rpc_service, mock_event_manager):
        response = _send(app_model, ApiCommand.EMERGENCY_STOP)
        assert response.result == ApiCommandRequestResult.SUCCESS
        assert response.data == {"reason": EmergencyControlSource.RPC_SERVICE}
        assert app_model.behavior.algorithm.algo_paused
        assert len(_event_contexts(mock_event_manager, ApiEventKind.emergencyStop)) == 1
