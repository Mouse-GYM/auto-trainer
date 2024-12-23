from typing import Optional

from autotrainer.core import ObservableObject
from autotrainer.inference import PoseResponse
from autotrainer.behavior import SegmentationConfiguration, DetectionConfiguration


class MockInference(ObservableObject):
    """
    Provides pose algorithm events for testing.
    """
    def __init__(self):
        super().__init__(event_names=("pose_changed",))

        self.segmentation_configuration : Optional[SegmentationConfiguration] = None
        self.detection_configuration: Optional[DetectionConfiguration] = None

    # region Mocks
    # Methods that provide the expected response from other parts of the system that are not being tested here.
    def mock_send_response(self, pellet_seen: bool, mouse_seen: bool):
        parts_flag = {"Pellet": pellet_seen, "Tongue": mouse_seen, "Nose": mouse_seen}

        parts_flags = (parts_flag, parts_flag, parts_flag)

        response = PoseResponse(sequence=1, parts_flags=parts_flags, locations=[])

        self.pose_changed(response)

    def mock_complete_segmentation(self, success: bool):
        self.segmentation_configuration.complete(self.segmentation_configuration.nonce, success)

    def mock_complete_detection(self, success: bool):
        self.detection_configuration.complete(self.segmentation_configuration.nonce, success)

    # region InferenceProtocol
    # Members required to implement InferenceProtocol
    @property
    def pose_algorithm(self):
        return self

    def perform_segmentation(self, configuration: SegmentationConfiguration):
        self.segmentation_configuration = configuration

    def perform_detection(self, configuration: DetectionConfiguration):
        self.detection_configuration = configuration

    def perform_live(self):
        pass
