import contextlib
import logging
import queue
import sys
import time
from functools import partial
from pathlib import Path
from typing import List, Any
from unittest import mock

import pytest

from autotrainer.behavior import TunnelDeviceProtocol, SystemMachine, PelletDeviceProtocol, PelletState
from autotrainer.core import EventManager, SensorAnalysis, MessageHandler, SystemMessageHandler
from autotrainer.core import ProjectInfo
from autotrainer.device import DeviceConnectionProtocol
from autotrainer.inference import PoseAlgorithm, PoseResponse, InferenceStatus
from autotrainer.video import CaptureProcessStatus

from tools.acquisition.model.inference_model import InferenceModel



def property_value_save_transitions(old_value, new_value, *, transitions: List[Any]):
    """Helper to record the transitions of value of a property
    Also ensure/assert that the transitions are consistent.
    """
    if len(transitions) > 0:
        assert transitions[-1] == old_value
        assert new_value != old_value
    transitions.append(new_value)


@pytest.fixture
def project_info(tmp_path):
    root = tmp_path.joinpath("root")
    root.mkdir()
    prj = ProjectInfo(root=root.as_posix())
    yield prj


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
    inference = InferenceModel(pose_algorithm=pose_algo)
    inference._set_status(InferenceStatus.live)
    return inference


@pytest.fixture
def system_msg_queue():
    q = queue.Queue()
    yield q
    logging.info("system msg qsize after use: %s", q.qsize())


@pytest.fixture
def system_msg_handler(system_msg_queue):
    # now/atm unused
    handler = SystemMessageHandler(system_msg_queue)
    handler.start()
    yield handler
    handler.request_terminate()
    handler.wait_terminated()


@pytest.fixture
def machine(tunnel_device, pellet_device, inference, project_info):
    machine = SystemMachine(
        tunnel_device=tunnel_device,
        pellet_device=pellet_device,
        analysis=SensorAnalysis(),
        inference=inference,
        project_info=project_info,
    )
    machine.algorithm.capture_status = CaptureProcessStatus.RUNNING
    return machine


class MockSystemMachine:
    """Allow make test case on a fully prepared 'SystemMachine' instance, with many helper methods included"""

    def _init(self, machine: SystemMachine):
        self._ts_now = 0
        self._machine = machine
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

    @pytest.fixture(autouse=True)
    def __machine(self, machine: SystemMachine) -> SystemMachine:  # noqa
        self._init(machine)
        yield machine  # noqa

    @property
    def machine(self) -> SystemMachine:
        return self._machine

    @property
    def inference(self) -> InferenceModel:
        return self._machine._inference

    @property
    def pellet(self):
        return self._machine.pellet

    @property
    def msg_handler(self) -> MessageHandler:
        return self._machine._msg_handler

    @contextlib.contextmanager
    def mock_perform_segmentation(self):
        """Mock the inference.perform_segmentation() method"""
        with mock.patch.object(self.inference, 'perform_segmentation') as m_seg:
            yield m_seg

    @contextlib.contextmanager
    def mock_perform_detection(self):
        """Mock the inference.perform_detection() method"""
        with mock.patch.object(self.inference, 'perform_detection') as m_det:
            yield m_det

    def mock_pose_response(self, pellet_seen: bool, mouse_seen: bool, triangle_seen: bool=True, ack_pellet: bool=False):
        """Send/trigger a PoseResponse via pose_algorithm.pose_changed event"""
        parts_flag = {
            "Pellet": pellet_seen,
            "Tongue": mouse_seen,
            "Nose": mouse_seen,
            "Triangle": triangle_seen,
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
        self.pellet._pellet_device_ack_received(self.pellet._api_status_token)

    def mock_pellet_missing(self, should_release: bool = True, was_covered: bool = False, mouse_seen: bool = False,
                            should_prerelease: bool = False):
        # Make sure we are beyond the required pellet missing time.
        # time.sleep(self.machine.algorithm.limits.pellet_missing_time + 0.1)

        self.mock_pose_response(False, mouse_seen)

        self.expect_pellet_delivery(should_release, was_covered, should_prerelease)

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

    def mock_complete_segmentation(self, success: bool):
        seg_cfg = self._machine.intersession._segmentation_configuration
        seg_cfg.complete(seg_cfg.nonce, success)

    def mock_complete_detection(self, success: bool):
        det_cfg = self._machine.intersession._detection_configuration
        det_cfg.complete(det_cfg.nonce, success)

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
        algo._last_capture_status_change_perf_c -= algo.recording_age_release_pellet_threshold
        self.pellet.environment_changed(pellet_seen=True, must_release=True, caller="simulate start recording")


@pytest.fixture
def mock_system(machine):
    """Allow use BaseSystemMachineTest instance helper methods in a simple function test, without having to subclass,
    just use the 'mock_system' fixture"""
    instance = MockSystemMachine()
    # instance.machine_(machine)  # pytest fixture refuse direct call, so:
    instance._init(machine)
    yield instance

