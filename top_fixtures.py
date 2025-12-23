import contextlib
import logging
import queue

from pathlib import Path
from functools import partial
from typing import List, Any
from unittest import mock

import pytest

import autotrainer.core

from autotrainer.core import EventManager, SensorAnalysis, MessageHandler, SystemMessageHandler, ProjectInfo
from autotrainer.core.multiproc import make_daemon_timer, DaemonTimer
from autotrainer.device import MotorConfigurationFile, CompoundMovements
from autotrainer.inference.analysis import IntersessionResponse

from autotrainer.video import CaptureProcessStatus
from autotrainer.inference import PoseAlgorithm, PoseResponse, InferenceStatus

from autotrainer.behavior import TunnelDeviceProtocol, SystemMachine, PelletDeviceProtocol, PelletState, \
    BehaviorAlgorithm, InferenceProtocol


logger = logging.getLogger(__name__)


repo_root_this_dir = Path(__file__).parent  # supposed to be the repo root/top dir
repo_root_tests_subdir = repo_root_this_dir.joinpath("tests")


fake_perf_now = 0  # used to control time.perf_counter() in BehaviorAlgo/SystemMachine/PelletMachine/Intersession


@pytest.fixture(autouse=True)
def reset_fake_perf_now():
    global fake_perf_now
    fake_perf_now = 0


def get_fake_perf_now():
    global fake_perf_now
    fake_perf_now += 1e-9  # convenience, so that any call to it will get a different value than the previous
    return fake_perf_now


@pytest.fixture(autouse=True)
def auto_close_event_manager():
    # allow to close the EventManager and have its worker thread exits gracefully (on each end of test case)
    yield
    EventManager.try_close_default()


@pytest.fixture(autouse=True, scope="session")
def auto_set_misc_log_level():
    # some logger we don't want too verbose in any case
    logging.getLogger('transitions').setLevel(logging.INFO)


@pytest.fixture(autouse=True)
def motor_config(monkeypatch):
    monkeypatch.setattr(MotorConfigurationFile, "DEFAULT_LOCATION",
                        repo_root_tests_subdir.joinpath(MotorConfigurationFile.DEFAULT_LOCATION.name))
    monkeypatch.setattr(CompoundMovements, "DEFAULT_LOCATION",
                        repo_root_tests_subdir.joinpath(CompoundMovements.DEFAULT_LOCATION.name))


@pytest.fixture
def project_info(tmp_path):
    root = tmp_path.joinpath("root")
    root.mkdir()
    prj = ProjectInfo(root=root.as_posix())
    yield prj


##


def property_value_save_transitions(old_value, new_value, *, transitions: List[Any]):
    """Helper to record the transitions of value of a property
    Also ensure/assert that the transitions are consistent.
    """
    if len(transitions) > 0:
        assert transitions[-1] == old_value
        assert new_value != old_value
    transitions.append(new_value)


@pytest.fixture(scope='session', autouse=True)
def _disable_timers():
    def disabled_daemon_timer(delay, func):
        # raise RuntimeError(f"Disabled daemon timer {delay} -> {func}")
        logging.warning("DaemonTimer disabled for delay=%s @ %s", delay, func)
        return mock.create_autospec(DaemonTimer)
    with mock.patch(f"{DaemonTimer.__module__}.{DaemonTimer.__name__}", new=disabled_daemon_timer):
        yield


@pytest.fixture
def tunnel_device():
    return mock.create_autospec(TunnelDeviceProtocol)


@pytest.fixture
def pellet_device():
    return mock.create_autospec(PelletDeviceProtocol)


@pytest.fixture
def pose_algo():
    return PoseAlgorithm()


@pytest.fixture
def inference(pose_algo):
    inference = InferenceProtocol()
    inference.status = InferenceStatus.live
    yield inference
    # inference.terminate()


@pytest.fixture
def system_msg_queue():
    q = queue.Queue()
    try:
        yield q
    finally:
        logging.info("system msg qsize after use: %s", q.qsize())
        while True:
            try:
                q.get_nowait()
                q.task_done()
            except queue.Empty:
                break
        q.join()


@pytest.fixture
def sensor_analysis():
    s = SensorAnalysis()
    try:
        yield s
    finally:
        s.stop()


@pytest.fixture
def system_msg_handler(system_msg_queue, sensor_analysis):
    handler = SystemMessageHandler(system_msg_queue, sensor_analysis=sensor_analysis)
    handler.start()
    try:
        yield handler
    finally:
        handler.request_terminate()
        handler.wait_terminated()


@pytest.fixture
def machine(project_info, tunnel_device, pellet_device, inference, sensor_analysis, monkeypatch) -> SystemMachine:
    # Disable algo handler thread
    assert BehaviorAlgorithm._no_handler_thread is False
    monkeypatch.setattr(BehaviorAlgorithm, "_no_handler_thread", True)
    assert BehaviorAlgorithm._no_handler_thread is True

    # cur = autotrainer.core.get_perf_now()
    # assert cur > 0
    monkeypatch.setattr(autotrainer.core, "_get_perf_now", get_fake_perf_now)
    # assert autotrainer.core.get_perf_now() == 0

    #
    machine = SystemMachine(
        tunnel_device=tunnel_device,
        pellet_device=pellet_device,
        analysis=sensor_analysis,
        inference=inference,
        project_info=project_info,
    )
    algo = machine.algorithm
    algo.capture_status = CaptureProcessStatus.RUNNING
    algo.pellet_hand_uncover_distance = None  # disabled
    return machine


class MockSystemMachine:
    """Allow make test case on a fully prepared 'SystemMachine' instance, with many helper methods included"""

    def _init(self, machine: SystemMachine):
        self._ts_now = 0
        self._machine: SystemMachine = machine
        self._load_cell = machine._analysis.load_cell_monitor  # noqa
        # register state_changed (and system_state_changed for algo at end) transition recorder,
        # so that can be used to ensure/assert that the given states have passed through all the desired values,
        # and in any desired specific order - or not.
        self.machine_state_trans = []
        machine.events.state_changed += partial(
            property_value_save_transitions, transitions=self.machine_state_trans)
        self.pellet_state_trans = []
        self.pellet.events.state_changed += partial(
            property_value_save_transitions, transitions=self.pellet_state_trans)
        self.intersession_state_trans = []
        machine.intersession.events.state_changed += partial(
            property_value_save_transitions, transitions=self.intersession_state_trans)

    @staticmethod
    def increment_perf_now(inc: float=60):
        global fake_perf_now
        fake_perf_now += inc

    @pytest.fixture()
    def machine(self, machine: SystemMachine) -> SystemMachine:  # noqa
        self._init(machine)
        yield machine  # noqa

    @property
    def inference(self) -> InferenceProtocol:
        return self._machine._inference

    @property
    def pellet(self):
        return self._machine.pellet

    @property
    def msg_handler(self) -> MessageHandler:
        return self._machine._msg_handler

    #

    @contextlib.contextmanager
    def mock_analysis(self, results: IntersessionResponse):
        with contextlib.ExitStack() as stack:
            stack.enter_context(self.mock_perform_segmentation())
            stack.enter_context(self.mock_perform_detection())
            self.mock_complete_segmentation(True)
            self.mock_complete_detection(True)
            self._machine._inference.detection_result_ready(results)
            yield

    @contextlib.contextmanager
    def mock_perform_segmentation(self):
        """Mock the inference.perform_segmentation() method"""
        with mock.patch.object(self.inference, 'perform_segmentation') as m_seg:
            yield m_seg

    def mock_complete_segmentation(self, success: bool):
        seg_cfg = self._machine.intersession._segmentation_configuration
        seg_cfg.complete(seg_cfg.nonce, success)

    @contextlib.contextmanager
    def mock_perform_detection(self):
        """Mock the inference.perform_detection() method"""
        with mock.patch.object(self.inference, 'perform_detection') as m_det:
            yield m_det

    def mock_complete_detection(self, success: bool):
        det_cfg = self._machine.intersession._detection_configuration
        det_cfg.complete(det_cfg.nonce, success)

    def mock_pose_response(
        self,
        *,
        pellet_seen: bool,
        mouse_seen: bool=False,
        triangle_seen: bool=True,
        diamond_seen: bool=True,
        ack_pellet: bool=False,
    ):
        """Send/trigger a PoseResponse via pose_algorithm.pose_changed event"""
        parts_flag = {
            "Pellet": pellet_seen,
            "Tongue": mouse_seen,
            "Nose": mouse_seen,
            "Triangle": triangle_seen,
            "Diamond": diamond_seen,
        }
        parts_flags = (parts_flag, parts_flag, parts_flag)
        response = PoseResponse(sequence=1, parts_flags=parts_flags, locations=[])
        # self.inference.pose_algorithm.pose_changed(response)
        self.inference.pose_response_ready(response)
        if self.pellet._api_status_token is not None and ack_pellet:
            self.pellet._pellet_device_ack_received(self.pellet._api_status_token)

    def expect_cover_command(self):
        # An explicit cover command should have been set.  Should be in covering state and have an ack from the command.
        assert self.pellet.state == PelletState.covering
        self.mock_pellet_ack()

    def mock_pellet_ack(self):
        """Ack the previous sent pellet command"""
        token = self.pellet._api_status_token
        assert token is not None
        self.increment_perf_now(1e-9)
        self.pellet._pellet_device_ack_received(token)

    def mock_pellet_missing(self, mouse_seen: bool = False):
        self.mock_pose_response(pellet_seen=False, mouse_seen=mouse_seen)
        # make sure we are beyond the required pellet missing time:
        self.increment_perf_now(self._machine.algorithm.pellet_missing_time + 1e-9)
        self.mock_pose_response(pellet_seen=False, mouse_seen=mouse_seen)

    def expect_pellet_delivery(self, should_release: bool = True, was_covered: bool = False,
                               should_prerelease: bool = False):
        """
        Convenience method that uses the mock pellet device reader to send the expected ack() to the machine for the
        expected transitions.  This method assumes that load_pellet() has already been triggered via pose response or
        whatever applicable mechanism.

        :param should_release: whether the pellet is expected to be released (vs. left covered)

        :param was_covered: whether the pellet should already be in the covered state

        :param should_prerelease: whether movement should include the prerelease step
        """

        pellet = self.pellet
        ack_received = pellet._pellet_device_ack_received

        if not was_covered:
            assert pellet.state == PelletState.loading

            ack_received(pellet._api_status_token)
            if should_prerelease:
                assert pellet.state == PelletState.prerelease
                ack_received(pellet._api_status_token)

            assert pellet.state == PelletState.sending

            ack_received(pellet._api_status_token)

        if should_release:
            if not should_prerelease:
                assert pellet.state == PelletState.releasing
                ack_received(pellet._api_status_token)

            assert pellet.state == PelletState.monitoring

    def make_load_cell_active(self):
        # NB: this could be moved to auto-trainer-core (where load_cell_monitor is defined),
        # so to be reused by auto-trainer-core/tests dedicated to load cell monitor.
        batch_count = self._load_cell._engaged_batch_count
        for _ in range(2 * batch_count):
            self._ts_now += self._load_cell.config.threshold_duration / batch_count + 0.001
            self._load_cell.update(self._load_cell.config.weight_active_threshold + 0.001, self._ts_now, self._ts_now)

    def make_load_cell_inactive(self):
        batch_count = self._load_cell._engaged_batch_count
        for _ in range(3 * batch_count):
            self._ts_now += self._load_cell.config.min_post_event_hold_duration / batch_count + 0.001
            self._load_cell.update(self._load_cell.config.weight_inactive_threshold - 0.001, self._ts_now, self._ts_now)

    def make_recording_aged_enough(self):
        algo = self._machine.algorithm
        algo.capture_status = CaptureProcessStatus.RECORDING
        self.increment_perf_now(algo.recording_age_release_pellet_threshold)


@pytest.fixture()
def mock_system(machine) -> MockSystemMachine:
    """Allow use BaseSystemMachineTest instance helper methods in a simple function test, without having to subclass,
    just use the 'mock_system' fixture"""
    instance = MockSystemMachine()
    # instance.machine_(machine)  # pytest fixture refuse direct call, so:
    instance._init(machine)
    return instance
