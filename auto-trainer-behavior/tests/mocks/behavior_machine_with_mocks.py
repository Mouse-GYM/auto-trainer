import time

from autotrainer.behavior import BehaviorAlgorithm, BehaviorLimits,  SystemMachine, InferenceState
from autotrainer.core import ProjectInfo

from .mock_headfix import MockHeadfix
from .mock_pellet_delivery import MockPelletDelivery
from .mock_pose_algorithm import MockPoseAlgorithm


class BehaviorMachineWithMocks(SystemMachine):
    """
    State machine that automatically creates mock interfaces for testing and provides convenience methods for multi-step
    behavior.
    """

    def __init__(self, algorithm: BehaviorAlgorithm = None, limits: BehaviorLimits = None):
        self._mock_headfix = MockHeadfix()
        self._mock_pellet = MockPelletDelivery()
        self._mock_pose = MockPoseAlgorithm()

        limits = limits if limits is not None else BehaviorLimits()

        algorithm = algorithm if algorithm is not None else BehaviorAlgorithm(limits)

        super().__init__(algorithm, self._mock_headfix, self._mock_headfix, self._mock_pellet, self._mock_pellet,
                         self._mock_pose)

    @property
    def headfix(self):
        return self._mock_headfix

    @property
    def pellet(self):
        return self._mock_pellet

    @property
    def pose(self):
        return self._mock_pose

    def lose_pellet(self, should_release: bool = True, was_covered: bool = False, mouse_seen: bool = False):
        # Make sure we are beyond the required pellet missing time.
        time.sleep(self.algorithm.limits.pellet_missing_time + 0.1)

        self.pose.send_response(False, mouse_seen)

        self.expect_pellet_delivery(should_release, was_covered)

    def expect_pellet_delivery(self, should_release: bool = True, was_covered: bool = False):
        """
        Convenience method that uses the mock pellet device reader to send the expected ack() to the machine for the
        expected transitions.  This method assumes that load_pellet() has already been triggered via pose response or
        whatever applicable mechanism.

        :param should_release: whether the pellet is expected to be released (vs. left covered)

        :param was_covered: whether the pellet should already be in the covered state
        """

        if not was_covered:
            assert self.inference.state == InferenceState.loading

            self.pellet.send_ack()

            assert self.inference.state == InferenceState.sending

            self.pellet.send_ack()

        if should_release:
            assert self.inference.state == InferenceState.releasing

            self.pellet.send_ack()

            assert self.inference.state == InferenceState.monitoring
