import collections
import copy
import contextlib
import logging
import math
import multiprocessing
import platform
import queue
import sys
import threading
import time
from multiprocessing import synchronize

from pathlib import Path
from functools import partial
from typing import List, Any, Optional, Union, ContextManager, Generator, Callable, Dict
from unittest import mock

import pytest
import verboselogs

import autotrainer.core
from autotrainer.behavior.behavior_algorithm import BehaviorAlgoStatus

from autotrainer.core import SensorAnalysis, MessageHandler, SystemMessageHandler, ProjectInfo
from autotrainer.core.analysis import detector
from autotrainer.core.message.message_handler import CommandResult
from autotrainer.core.multiproc import make_daemon_timer, DaemonTimer, get_mp_ctx
from autotrainer.core.testing import get_api_event_context, get_current_simulate_perf_now, get_mock_event_manager, \
    has_api_event_kind, increase_simulate_perf_now
from autotrainer.device import MotorConfigurationFile, CompoundMovements, can_device
from autotrainer.inference.analysis import IntertrialResponse

from autotrainer.core.capture import CaptureProcessStatus
from autotrainer.inference import PoseAlgorithm, PoseResponse, InferenceStatus

from autotrainer.behavior import TunnelDeviceProtocol, SystemMachine, PelletDeviceProtocol, BehaviorAlgorithm, \
    InferenceProtocol, SystemState
from autotrainer.core.diamond_triangle_config import DiamondTriangleOffsetConfig
from autotrainer.behavior.pellet import PelletState
from tools.acquisition.model.behavior_model import BehaviorModel
from tools.acquisition.model.hardware_model import HardwareModel
from tools.acquisition.model.user_preferences import UserPreferences

logger = logging.getLogger(__name__)


repo_root_dir = Path(__file__).parent  # supposed to be the repo root/top dir
repo_root_tests_subdir = repo_root_dir.joinpath("tests")


def nullify_attributes(obj, *, filter_attr=lambda a: not a.startswith('__')):
    """This is used to help prevent reference cycle/loops,
    which makes it harder for Python to free such objects,
    and sometimes can even possibly lead to resources not freed at all, at least during testing."""
    for attr in list(vars(obj)):
        if filter_attr(attr):
            setattr(obj, attr, None)


@pytest.fixture(autouse=True)
def force_use_emulation_iface(monkeypatch, _check_threads):
    # NB: this is used in conjunction of conftest:os.environ.setdefault('AUTOTRAINER_FORCE_CAN_EMULATION_IFACE' ..)
    # for current process:
    assert hasattr(can_device, "HAVE_CAN_DEVICE")
    monkeypatch.setattr(can_device, "HAVE_CAN_DEVICE", False)
    # for subprocesses:
    monkeypatch.setenv('AUTOTRAINER_FORCE_CAN_EMULATION_IFACE', "1")


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


@pytest.fixture(scope="function")
def mp_manager(_lsof_del_shm, _check_threads):
    mgr = get_mp_ctx().Manager()
    try:
        with mgr:
            yield mgr
    finally:
        try:
            mgr.join(1)
        except Exception as err:
            print(err)


@pytest.fixture(autouse=True)
def diamond_config_path(monkeypatch):
    path = repo_root_tests_subdir.joinpath("diamond_triangle_offset.yaml")
    monkeypatch.setattr(DiamondTriangleOffsetConfig, "DEFAULT_CONFIG_PATH", path)
    assert DiamondTriangleOffsetConfig.DEFAULT_CONFIG_PATH is path
    return path


@pytest.fixture
def diamond_triangle_config(diamond_config_path) -> DiamondTriangleOffsetConfig:
    return DiamondTriangleOffsetConfig.load_config(diamond_config_path)


@pytest.fixture
def trainer_config_dir(tmp_path):
    cfg_dir = tmp_path.joinpath("Autotrainer")
    cfg_dir.mkdir()
    return cfg_dir


@pytest.fixture
def animals_dir(tmp_path):
    path = tmp_path.joinpath("animals")
    path.mkdir()
    return path


@pytest.fixture
def settings_ini_path(tmp_path):
    return tmp_path.joinpath("settings.ini")


@pytest.fixture
def user_pref(
    tmp_path,
    trainer_config_dir,
    animals_dir,
    settings_ini_path,
) -> UserPreferences:  # noqa
    pref = UserPreferences(settings_file_path=settings_ini_path)
    pref.configuration_location = trainer_config_dir
    pref.animal_location = animals_dir
    p = tmp_path.joinpath("logs")
    p.mkdir()
    pref.log_location = p
    pref.log_level = int(verboselogs.VERBOSE)
    return pref


def collect_log_queue_to_caplog(log_queue, *, timeout: float=0.1, max_duration: float=5):
    """Drain the log until 1 "full" timeout occurs trying to read a record, or max_duration is reached"""
    p_begin = time.perf_counter()
    p_end = p_begin + max_duration
    while True:
        if time.perf_counter() > p_end:
            pytest.fail("unexpected too long duration collecting log record queue")
            break
        try:
            record = log_queue.get(timeout=timeout)
        except queue.Empty:
            break
        logging.getLogger(record.name).handle(record)


@pytest.fixture
def capture_multiprocess_logs(caplog) -> multiprocessing.Queue:  # noqa
    """Listens to a multiprocessing queue and forwards entries to caplog."""
    log_queue = multiprocessing.Queue()
    try:
        yield log_queue  # noqa
    finally:
        log_queue.close()
        log_queue.join_thread()


@pytest.fixture
def make_log_dict_multiproc(capture_multiprocess_logs, monkeypatch):
    def wrapped_make_log_dict():
        return {
            'version': 1,
            'disable_existing_loggers': False,
            'handlers': {
                'queue': {
                    'class': 'autotrainer.core.logging.WithThreadIdQueueHandler',
                    'queue': capture_multiprocess_logs,
                    'level': logging.NOTSET,  # pass everything to the listener
                }
            },
            # root logger is here:
            'root': {
                'handlers': ['queue'],
                # with its own level here:
                'level': logging.NOTSET,  # root_log_level,
                # FORCE NOTSET to relay everything so that file handler can properly get DEBUG as well
            },
            # but eventual level of other loggers have to be defined here:
            'loggers': copy.deepcopy(autotrainer.core.logging._limit_loggers_level),  # noqa
        }
    return wrapped_make_log_dict


##


def property_value_save_transitions(old_value, new_value, *, transitions: List[Any]):
    """Helper to record the transitions of value of a property
    Also ensure/assert that the transitions are consistent.
    """
    if len(transitions) > 0:
        assert transitions[-1] == old_value
        assert new_value != old_value
    transitions.append(new_value)


@pytest.fixture
def tunnel_device() -> TunnelDeviceProtocol:
    return mock.create_autospec(TunnelDeviceProtocol)


@pytest.fixture
def pellet_device() -> PelletDeviceProtocol:
    return mock.create_autospec(PelletDeviceProtocol)


@pytest.fixture
def pose_algo():
    return PoseAlgorithm()


class VoidInference(InferenceProtocol):

    def __init__(self):
        super().__init__()
        self._stop_recorded_event = threading.Event()  # noqa

    @property
    def pose_parts(self) -> List[str]:
        return []

    @property
    def stop_recorded_event(self) -> synchronize.Event:
        # still required,
        # could maybe be added to InferenceProtocol, which is more actually InferenceBase class...
        return self._stop_recorded_event


@pytest.fixture
def inference() -> VoidInference:
    inference = VoidInference()
    inference.status = InferenceStatus.live
    yield inference
    # inference.terminate()


@pytest.fixture
def system_msg_queue():
    # Unused
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
def sensor_analysis(mock_get_perf_now, monkeypatch) -> SensorAnalysis:  # noqa
    # ensure we don't have daemon or asynchronous detectors during tests
    for det_cls in detector.registered_detector_classes:
        monkeypatch.setattr(det_cls, "use_daemon", False)

    s = SensorAnalysis()
    try:
        yield s  # noqa
    finally:
        s.stop()


@pytest.fixture
def system_msg_handler(system_msg_queue, sensor_analysis):
    # Unused
    handler = SystemMessageHandler(system_msg_queue, sensor_analysis=sensor_analysis)
    handler.start()
    try:
        yield handler
    finally:
        handler.request_terminate()
        handler.wait_terminated()


class FakeMsgQueue:

    def put_nowait(self, item):
        pass
    def put(self, *args, **kwargs):
        pass
    def get(self, *args, **kwargs):
        raise RuntimeError("not supposed to happen")
    def get_nowait(self):
        raise RuntimeError("not supposed to happen")


class FakeSystemMsgHandler(SystemMessageHandler):

    def __init__(self, input_queue, *, sensor_analysis):
        super().__init__(input_queue, sensor_analysis=sensor_analysis)

    def start(self):
        pass

    def request_terminate(self):
        pass

    def wait_terminated(self):
        pass


@pytest.fixture
def fake_msg_queue():
    return FakeMsgQueue()


@pytest.fixture
def fake_system_msg_handler(fake_msg_queue, sensor_analysis):
    return FakeSystemMsgHandler(fake_msg_queue, sensor_analysis=sensor_analysis)


@pytest.fixture
def machine(
    project_info,
    tunnel_device,
    pellet_device,
    inference,
    sensor_analysis,
    monkeypatch,
    mock_get_perf_now,
    fake_system_msg_handler,
) -> SystemMachine:
    # Disable algo handler thread
    assert BehaviorAlgorithm._no_handler_thread is False
    monkeypatch.setattr(BehaviorAlgorithm, "_no_handler_thread", True)
    assert BehaviorAlgorithm._no_handler_thread is True

    del mock_get_perf_now  # not needed here, only used for side effect
    #
    inference.project = project_info
    #
    machine = SystemMachine(
        tunnel_device=tunnel_device,
        pellet_device=pellet_device,
        analysis=sensor_analysis,
        inference=inference,
        msg_handler=fake_system_msg_handler,
    )
    machine.project = project_info
    algo = machine.algorithm
    # most tests rely on:
    cfg = algo.pellet_delivery_config
    cfg.is_enabled = True
    cfg.is_pellet_cover_enabled = True
    cfg.pellet_send_wait_delay = 0
    algo.record_prebuffer_duration = 0
    algo.pellet_uncover_delay = 0
    algo.pellet_uncover_y_dcs = -math.inf
    algo.trial_minimum_duration = 0  # needed for most current tests
    # might be needed to reset:
    algo.capture_status = CaptureProcessStatus.RUNNING
    algo.status = BehaviorAlgoStatus.ANIMAL_IN_TRAINING
    machine.pellet.state = PelletState.monitoring  # force monitoring for current tests
    return machine


class FifoExitStack(contextlib.ExitStack):
    _exit_callbacks: collections.deque

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._exit_callbacks = collections.deque(reversed(list(self._exit_callbacks)))
        super().__exit__(exc_type, exc_val, exc_tb)


class MockSystemMachine:
    """Allow make test case on a fully prepared 'SystemMachine' instance, with many helper methods included"""

    def _init(self, machine: SystemMachine):
        self._machine: SystemMachine = machine
        self._do_init_mock_analysis(machine)
        self.project = machine.project
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
        self.intertrial_state_trans = []
        machine.intertrial.events.state_changed += partial(
            property_value_save_transitions, transitions=self.intertrial_state_trans)
        self._pose_response_idx = 0

    increment_perf_now = staticmethod(increase_simulate_perf_now)

    get_current_perf_now = staticmethod(get_current_simulate_perf_now)

    def _do_init_mock_analysis(self, machine):
        del machine  # depends on it for self.inference:
        m_perf_seg = mock.patch.object(self.inference, 'perform_segmentation')
        self._perf_seg_m = m_perf_seg.start()
        m_perf_det = mock.patch.object(self.inference, 'perform_detection')
        perf_det = m_perf_det.start()
        self._perf_det_m = perf_det

    @property
    def m_perf_seg(self) -> mock.MagicMock:
        return self._perf_seg_m

    @property
    def m_perf_det(self) -> mock.MagicMock:
        return self._perf_det_m

    @pytest.fixture(autouse=True)
    def _attach_request(self, request):
        self._pytest_request = request

    @pytest.fixture(autouse=True)
    def machine(self, machine: SystemMachine, _attach_request) -> SystemMachine:  # noqa
        self._init(machine)
        try:
            yield machine  # noqa
        finally:
            algo = machine.algorithm
            algo.top_camera_presence_detection = None
            nullify_attributes(self)

    @property
    def system_machine(self) -> SystemMachine:
        return self._machine

    @property
    def algo(self):
        return self._machine.algorithm

    @property
    def sensor_analysis(self):
        return self._machine.analysis

    @property
    def inference(self) -> InferenceProtocol:
        return self._machine._inference  # noqa

    @property
    def pellet(self):
        return self._machine.pellet

    @property
    def msg_handler(self) -> MessageHandler:
        return self._machine._msg_handler

    @property
    def tunnel_dev(self) -> Union[mock.MagicMock, TunnelDeviceProtocol]:
        return self._machine._tunnel_device

    @property
    def pellet_dev(self) -> Union[mock.MagicMock, PelletDeviceProtocol]:
        return self._machine._pellet_device

    #

    def start_trial_in_tunnel(self, set_recording_status: bool = False):
        algo = self.algo
        self.make_load_cell_active()
        if set_recording_status:
            algo.set_capture_status(CaptureProcessStatus.RECORDING)
        assert self._machine.state == SystemState.tunnel

    def exit_tunnel(self):
        assert self._machine.state != SystemState.cage
        load_cell = self.sensor_analysis.load_cell_monitor
        if load_cell.is_engaged:
            logger.info("exiting tunnel with load-cell")
            load_cell.is_engaged = False
        else:
            logger.info("exiting tunnel with manual")
            self._machine.exit_tunnel(reason="manual")

    @contextlib.contextmanager
    def patch_timer(self, place, new=None) -> ContextManager[Union[mock.MagicMock, DaemonTimer]]:  # noqa
        kw = {"autospec": DaemonTimer} if new is None else {"new": new}
        with mock.patch(place, **kw) as mock_t:
            # for some reason the finished event isn't present on the mocks, despite the autospec. so set it:
            mock_finished = mock_t.return_value.finished = mock.create_autospec(threading.Event)
            mock_finished.is_set.return_value = False
            yield mock_t  # noqa

    @contextlib.contextmanager
    def mock_analysis(
        self, *,
        stack: Optional[FifoExitStack]=None,
        project: Optional[ProjectInfo] = None,
        segmentation_ok: bool = True,
        detection_ok: bool = True,
        detection_result: Optional[IntertrialResponse] = None,
        seg_conc_func: Callable = lambda: None,
        det_conc_func: Callable = lambda: None,
    ):
        def wrapped(used_stack):
            self.make_analysis(
                used_stack,
                project=project,
                segmentation_ok=segmentation_ok, detection_ok=detection_ok, detection_result=detection_result,
                seg_conc_func=seg_conc_func, det_conc_func=det_conc_func,
            )
        if stack is None:
            with FifoExitStack() as stack:
                wrapped(stack)
                yield
        else:
            wrapped(stack)
            yield

    def make_analysis(
        self,
        stack: FifoExitStack, *,
        project: Optional[ProjectInfo] = None,
        segmentation_ok: bool = True,
        detection_ok: bool = True,
        detection_result: Optional[IntertrialResponse] = None,
        seg_conc_func: Callable = lambda: None,
        det_conc_func: Callable = lambda: None,
    ):
        if project is None:
            project = self._machine.project.to_local_value()
        if detection_result is None:
            detection_result = IntertrialResponse()
        detection_result: IntertrialResponse

        @contextlib.contextmanager
        def s1():
            yield
            seg_conc_func()
            self.mock_complete_segmentation(segmentation_ok)
        stack.enter_context(s1())

        if segmentation_ok:
            @contextlib.contextmanager
            def s2():
                yield
                det_conc_func()
                if detection_ok:
                    logger.info("sending detection_result_ready")
                    self.inference.detection_result_ready(project, detection_result)
                self.mock_complete_detection(detection_ok)
            stack.enter_context(s2())

    @contextlib.contextmanager
    def mock_perform_segmentation(self):
        """Mock the inference.perform_segmentation() method"""
        with mock.patch.object(self.inference, 'perform_segmentation') as m_seg:
            yield m_seg

    def mock_complete_segmentation(self, success: bool):
        seg_cfg = self._machine.intertrial._segmentation_configuration
        logger.info("calling segmentation complete")
        assert seg_cfg is not None
        seg_cfg.complete(success)

    def mock_complete_detection(self, success: bool):
        det_cfg = self._machine.intertrial._detection_configuration
        assert det_cfg is not None
        det_cfg.complete(success)

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
        self._pose_response_idx += 1
        response = PoseResponse(
            sequence=self._pose_response_idx, parts_flags=parts_flags, locations=[],
            perf_c=autotrainer.core.get_perf_now())
        self.inference.pose_response_ready(response)
        if self.pellet._api_status_token is not None and ack_pellet:
            self.pellet._pellet_device_ack_received(self.pellet._api_status_token, CommandResult(succeeded=True))

    def expect_cover_command(self):
        # An explicit cover command should have been set.  Should be in covering state and have an ack from the command.
        assert self.pellet.state == PelletState.covering
        self.mock_pellet_ack()

    def mock_pellet_ack(self, until_none: bool=False, max_limit: int=45):
        """Ack the previous sent pellet command"""
        cur_ack = 0
        while True:
            token = self.pellet._api_status_token
            if token is None:
                break
            cur_ack += 1
            self.increment_perf_now(1e-9)
            (# self.pellet._pellet_device_ack_received
            self.msg_handler.ack_received
             (token, CommandResult(succeeded=True)))
            if not until_none:
                break
            if cur_ack > max_limit:
                raise RuntimeError("Too many consecutive pellet ack")

    def mock_pellet_missing(self, mouse_seen: bool = False):
        self.mock_pose_response(pellet_seen=False, mouse_seen=mouse_seen)
        # make sure we are beyond the required pellet missing time:
        self.increment_perf_now(self._machine.algorithm.pellet_missing_time + 1e-9)
        self.mock_pose_response(pellet_seen=False, mouse_seen=mouse_seen)

    def make_load_cell_active(self):
        # NB: this could be moved to auto-trainer-core (where load_cell_monitor is defined),
        # so to be reused by auto-trainer-core/tests dedicated to load cell monitor.
        batch_count = self._load_cell._engaged_batch_count
        for _ in range(2 * batch_count):
            self.increment_perf_now(self._load_cell.config.threshold_duration / batch_count + 0.001)
            p_now = self.get_current_perf_now()
            self._load_cell.update(
                self._load_cell.config.weight_active_threshold + 0.001, time.time(), int(p_now * 1e9)
            )

    def make_load_cell_inactive(self):
        batch_count = self._load_cell._engaged_batch_count
        for _ in range(3 * batch_count):
            self.increment_perf_now(self._load_cell.config.min_post_event_hold_duration / batch_count + 0.001)
            p_now = self.get_current_perf_now()
            self._load_cell.update(
                self._load_cell.config.weight_inactive_threshold - 0.001, time.time(), int(p_now * 1e9))

    @staticmethod
    def has_api_event(kind):
        return has_api_event_kind(kind)

    get_api_event_context = staticmethod(get_api_event_context)

    @property
    def m_post_event(self) -> mock.MagicMock:
        return get_mock_event_manager().post_event


@pytest.fixture
def mock_system(machine, request) -> MockSystemMachine:
    """Allow use BaseSystemMachineTest instance helper methods in a simple function test, without having to subclass,
    just use the 'mock_system' fixture"""
    instance = MockSystemMachine()
    instance._pytest_request = request
    # instance.machine_(machine)  # pytest fixture refuse direct call, so:
    instance._init(machine)
    return instance


@pytest.fixture
def hardware_model(fake_system_msg_handler, sensor_analysis) -> HardwareModel:  # noqa
    hard = HardwareModel(fake_system_msg_handler, sensor_analysis=sensor_analysis)
    try:
        yield hard  # noqa
    finally:
        hard.disconnect()


@pytest.fixture
def behavior_model(sensor_analysis, fake_system_msg_handler, hardware_model, inference) -> BehaviorModel:  # noqa
    # unused
    model = BehaviorModel(fake_system_msg_handler, sensor_analysis, hardware_model, inference)
    try:
        yield model  # noqa
    finally:
        BehaviorAlgorithm.close_algorithm_handler()
