from autotrainer.core import ObservableObject
from autotrainer.inference import PoseResponse


class MockPoseAlgorithm(ObservableObject):
    """
    Provides pose algorithm events for testing.
    """
    def __init__(self):
        super().__init__(event_names=("pose_changed",))

    # noinspection PyMethodMayBeStatic
    def get_part_index(self, name: str) -> int:
        if name == "Pellet":
            return 0
        else:
            return -1

    def send_response(self, pellet_seen: bool, mouse_seen: bool):
        parts_flag = {"Pellet": pellet_seen, "Tongue": mouse_seen, "Nose": mouse_seen}

        response = PoseResponse(sequence=1, parts_flag=parts_flag, locations=[])

        self.pose_changed(response)
