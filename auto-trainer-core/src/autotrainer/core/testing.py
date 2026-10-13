"""Pytest support for core's tests and for the tests of packages built on core.

Load this module as a plugin: `-p autotrainer.core.testing` in pytest's `addopts`, or
`pytest_plugins = ["autotrainer.core.testing"]` in a top-level conftest, listed before any plugin that imports
from it. It is deliberately not a `pytest11` entry point: its autouse fixtures would then apply to every pytest
session in any environment that has core installed.

Import plain helpers from here, never fixtures: a fixture imported into another module is registered a second
time. Needs pytest, from core's `test` extra; nothing in core imports this module.
"""
import datetime
import logging
import os
import subprocess
import threading
from typing import Any, Callable, Mapping, Optional
from unittest import mock

import pytest

import autotrainer.core
from autotrainer.core import EventInfo, EventManager, ProjectInfo
from autotrainer.core.event import event_manager
from autotrainer.core.multiproc import DaemonTimer


fake_perf_now = 0  # used to control time.perf_counter() in BehaviorAlgo/SystemMachine/PelletMachine/Intersession
_lock_fake_perf_now = threading.Lock()


def simulate_get_perf_now():
    global fake_perf_now
    with _lock_fake_perf_now:
        fake_perf_now += 1e-9  # convenience, so that any call to it will get a different value than the previous
        return fake_perf_now


def get_current_simulate_perf_now():
    return fake_perf_now


def increase_simulate_perf_now(delay: float = 60, refresh_func: Optional[Callable] = None):
    global fake_perf_now
    with _lock_fake_perf_now:
        fake_perf_now += delay


# for small diff of timers delay:
class AlmostEqualFloat(float):
    def __eq__(self, other):
        return abs(self - other) < 0.1


def _make_del_shm_sem_count():
    out = [
        line
        for line in subprocess.getoutput(f"lsof -np {os.getpid()}").splitlines()
        if "DEL" in line and "/dev/shm/sem" in line
    ]
    return len(out)


@pytest.fixture(autouse=True)
def _check_threads(request):
    if os.getenv("AUTOTRAINER_TEST_CHECK_NO_REMAINING_THREAD") == "0":
        yield
        return
    before = list(threading.enumerate())
    try:
        yield
    finally:
        after = [thread for thread in threading.enumerate() if thread.is_alive()]
        new = list(set(after) - set(before))
        if len(new) > 0:
            raise RuntimeError(f"detected remaining threads after test: {new} // before={before}")


_cnt_shm_sem_del_prev_before = 0
_cnt_shm_sem_del_prev_after = 0


@pytest.fixture(autouse=True)
def _lsof_del_shm(request, _check_threads):
    global _cnt_shm_sem_del_prev_before, _cnt_shm_sem_del_prev_after
    if not os.getenv("AUTOTRAINER_TEST_PROFILE_SHM_SEM"):
        yield
        return
    before = _make_del_shm_sem_count()
    if before < _cnt_shm_sem_del_prev_after:
        print(f"detected successful free of shm sem resource: {_cnt_shm_sem_del_prev_after} -> {before}")
    elif before > 0 and before != _cnt_shm_sem_del_prev_before:
        print(
            f"There are already {before} leaked shm sem at test start, "
            "this indicates the previous test have probably missed to close/free some shm resource",
        )
    _cnt_shm_sem_del_prev_before = before
    try:
        yield
    finally:
        after = _make_del_shm_sem_count()
        _cnt_shm_sem_del_prev_after = after
        if after > before:
            print(f"/dev/shm/sem DEL: {before} -> {after}")


class SimulatePerfNow:

    get_current_perf_now: Callable[[], float]
    increase_simulate_perf_now: Callable[[float], None]


@pytest.fixture
def mock_get_perf_now(monkeypatch) -> SimulatePerfNow:
    global fake_perf_now
    fake_perf_now = 0
    monkeypatch.setattr(autotrainer.core, "_get_perf_now", simulate_get_perf_now)
    obj = SimulatePerfNow()
    obj.get_current_perf_now = get_current_simulate_perf_now
    obj.increase_simulate_perf_now = increase_simulate_perf_now
    return obj


_m_event_mgr: Optional[mock.MagicMock] = None


@pytest.fixture()
def mock_event_manager(monkeypatch, _check_threads):
    real_manager = event_manager.EventManager
    real_post_api_event = real_manager.post_api_event
    real_post_event_content = real_manager.post_event_content
    m_event_mgr = mock.MagicMock(spec=real_manager)
    m_event_mgr.default.return_value = m_event_mgr
    m_event_mgr.post_api_event.side_effect = lambda *args, **kwargs: real_post_api_event(m_event_mgr, *args, **kwargs)
    m_event_mgr.post_event_content.side_effect = (
        lambda *args, **kwargs: real_post_event_content(m_event_mgr, *args, **kwargs)
    )
    # patch "default" function on real manager class:
    monkeypatch.setattr(real_manager, "default", mock.MagicMock(side_effect=lambda: m_event_mgr))
    # so that modules having already import the class, and using the default() function,
    # will still get the mocked instance.
    # Then, also patch the EventManager itself in the module:
    monkeypatch.setattr(event_manager, real_manager.__name__, m_event_mgr)
    global _m_event_mgr
    _m_event_mgr = m_event_mgr
    try:
        yield m_event_mgr
    finally:
        _m_event_mgr = None


def get_mock_event_manager() -> mock.MagicMock:
    if _m_event_mgr is None:
        raise RuntimeError("mock_event_manager not active")
    return _m_event_mgr


def has_api_event_kind(kind) -> bool:
    return any(call.args[0].kind == kind for call in get_mock_event_manager().post_event.call_args_list)


def get_api_event_context(kind) -> Optional[Mapping[str, Any]]:
    for call in get_mock_event_manager().post_event.call_args_list:
        info: EventInfo = call.args[0]
        if info.kind == kind:
            return info.context
    return None


@pytest.fixture(autouse=True)
def auto_close_event_manager(_check_threads):
    # allow to close the EventManager and have its worker thread exits gracefully (on each end of test case)
    try:
        yield
    finally:
        EventManager.try_close_default()


@pytest.fixture
def project_info(tmp_path) -> ProjectInfo:
    root = tmp_path.joinpath("root")
    # don't auto-create the root/base dir, most tests won't need it anyway.
    prj = ProjectInfo(
        device_id="agx-test-host",
        # explicitly provide the trial & when,
        # to get a "local"/not-shared ProjectInfo
        trial=1,
        when=datetime.datetime.fromtimestamp(0),
        root=root.as_posix(),
        camera_1="left",
        camera_2="right",
    )
    return prj


@pytest.fixture(scope="session", autouse=True)
def _disable_timers():
    def disabled_daemon_timer(delay, func):
        logging.warning("DaemonTimer disabled for delay=%s @ %s", delay, func)
        timer = mock.create_autospec(DaemonTimer)
        # for some reason the finished event isn't present on the mocks, despite the autospec. so set it:
        mock_finished = timer.finished = mock.create_autospec(threading.Event)
        mock_finished.is_set.return_value = True
        return timer
    obj_fqn = f"{DaemonTimer.__module__}.{DaemonTimer.__name__}"
    with mock.patch(obj_fqn, new=disabled_daemon_timer):
        yield


class MixinEvents:
    """Used to have thread event on detectors used in tests"""

    is_engaged: bool

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.check_in_progress_event = threading.Event()
        self.check_attempted = threading.Event()
        self.engaged_event = threading.Event()
        self.disengaged_event = threading.Event()
        if self.is_engaged:
            self.engaged_event.set()
        else:
            self.disengaged_event.set()

    def set_is_engaged(self, engaged):
        super().set_is_engaged(engaged)  # noqa
        if self.is_engaged:
            self.engaged_event.set()
            self.disengaged_event.clear()
        else:
            self.disengaged_event.set()
            self.engaged_event.clear()

    def _check_state(self, *, force: bool = False) -> Optional[float]:
        self.check_in_progress_event.set()
        try:
            next_delay = super()._check_state(force=force)
        finally:
            self.check_attempted.set()
        return next_delay
