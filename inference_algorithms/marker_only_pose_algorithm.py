from autotrainer.inference.pose_algorithms import register
from autotrainer.inference import PoseAlgorithm


@register("Marker Only")
class MarkerOnlyPoseAlgorithm(PoseAlgorithm):
    def __init__(self):
        super().__init__()
        self._pellet_part_index = -1
        self._star_part_index = -1

    def initialize(self):
        self._pellet_part_index = self.get_part_index("Pellet")
        self._star_part_index = self.get_part_index("Star")

    def process_frames(self, all_frames: list, left_frames: list, right_frames: list):
        if self._star_part_index == -1 or self._pellet_part_index == -1:
            return (0, 0, 0, 0), (0, 0, 0, 0)

        pellet1, star1 = self.find_parts(left_frames)
        pellet2, star2 = self.find_parts(right_frames)

        return (*pellet1, *star1), (*pellet2, *star2)

    def find_parts(self, frames: list) -> ((float, float), (float, float)):
        pellet = (0, 0)
        star = (0, 0)
        for pose in frames:
            if pose[self._pellet_part_index, 2] >= 0.9:
                pellet = pose[self._pellet_part_index, 0:2]
            if pose[self._star_part_index, 2] >= 0.9:
                star = pose[self._star_part_index, 0:2]
        return pellet, star
