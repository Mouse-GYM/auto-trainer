from autotrainer.behavior import SystemBehaviorMachine, BehaviorAlgorithm, InferenceState

from .mock_headfix_reader import MockHeadfixReader
from .mock_pellet_delivery import MockPelletDelivery
from .mock_pose_algorithm import MockPoseAlgorithm


class BehaviorMachineWithMocks(SystemBehaviorMachine):
    def __init__(self, properties: BehaviorAlgorithm = None):
        self._mock_headfix = MockHeadfixReader()
        self._mock_pellet = MockPelletDelivery()
        self._mock_pose = MockPoseAlgorithm()

        super().__init__(self._mock_headfix, self._mock_pellet, self._mock_pellet, self._mock_pose, properties)

    @property
    def headfix(self):
        return self._mock_headfix

    @property
    def pellet(self):
        return self._mock_pellet

    @property
    def pose(self):
        return self._mock_pose

    def expect_pellet_delivery(self, expect_release: bool = True, expected_release: bool = True):
        if expected_release:
            assert self.inference.state == InferenceState.loading

            self.pellet.send_ack()

            assert self.inference.state == InferenceState.sending

            self.pellet.send_ack()

        if expect_release:
            assert self.inference.state == InferenceState.releasing

            self.pellet.send_ack()

            assert self.inference.state == InferenceState.monitoring
