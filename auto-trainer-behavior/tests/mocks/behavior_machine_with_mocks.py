import tempfile
import time

from autotrainer.behavior import BehaviorAlgorithm, BehaviorLimits, SystemMachine, PelletState
from autotrainer.core import ProjectInfo

from .mock_headfix import MockHeadfix
from .mock_pellet_delivery import MockPelletDelivery
from .mock_inference import MockInference


class BehaviorMachineWithMocks(SystemMachine):
    """
    State machine that automatically creates mock interfaces for testing and provides convenience methods for multi-step
    behavior.
    """

    def __init__(self, algorithm: BehaviorAlgorithm = None, limits: BehaviorLimits = None):
        self._mock_headfix = MockHeadfix()
        self._mock_pellet = MockPelletDelivery()
        self._mock_inference = MockInference()
        self._project_info = ProjectInfo(root=tempfile.gettempdir(), device_id="123456", ensure_exists=False)

        limits = limits if limits is not None else BehaviorLimits()

        algorithm = algorithm if algorithm is not None else BehaviorAlgorithm(limits)

        super().__init__(algorithm, self._mock_headfix, self._mock_pellet, self._mock_pellet,
                         self._mock_inference, self._project_info)

    @property
    def mock_headfix(self):
        return self._mock_headfix

    @property
    def mock_pellet(self):
        return self._mock_pellet

    @property
    def mock_inference(self):
        return self._mock_inference

    def mock_pose_response(self, pellet_seen: bool, mouse_seen: bool):
        self.mock_inference.mock_send_response(pellet_seen, mouse_seen)

    def mock_pellet_seen(self, was_covered: bool = False, mouse_seen: bool = False):
        self.mock_pose_response(True, mouse_seen)

        if was_covered:
            assert self.inference.state == PelletState.releasing

            self.mock_pellet.send_ack()

            assert self.inference.state == PelletState.monitoring
        else:
            self.expect_pellet_delivery(True, was_covered)

    def mock_pellet_missing(self, should_release: bool = True, was_covered: bool = False, mouse_seen: bool = False):
        # Make sure we are beyond the required pellet missing time.
        time.sleep(self.algorithm.limits.pellet_missing_time + 0.1)

        self.mock_pose_response(False, mouse_seen)

        self.expect_pellet_delivery(should_release, was_covered)

    def expect_cover_command(self):
        # An explicit cover command should have been set.  Should be in covering state and have an ack from the command.
        assert self.inference.state == PelletState.covering

        self.mock_pellet.send_ack()

    def expect_pellet_delivery(self, should_release: bool = True, was_covered: bool = False):
        """
        Convenience method that uses the mock pellet device reader to send the expected ack() to the machine for the
        expected transitions.  This method assumes that load_pellet() has already been triggered via pose response or
        whatever applicable mechanism.

        :param should_release: whether the pellet is expected to be released (vs. left covered)

        :param was_covered: whether the pellet should already be in the covered state
        """

        if not was_covered:
            assert self.inference.state == PelletState.loading

            self.mock_pellet.send_ack()

            assert self.inference.state == PelletState.sending

            self.mock_pellet.send_ack()

        if should_release:
            assert self.inference.state == PelletState.releasing

            self.mock_pellet.send_ack()

            assert self.inference.state == PelletState.monitoring
