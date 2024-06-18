from autotrainer.inference.pose_algorithms import register
from inference_algorithms.marker_only_pose_algorithm import MarkerOnlyPoseAlgorithm


@register("Pellet Only")
class PelletOnlyPoseAlgorithm(MarkerOnlyPoseAlgorithm):
    def __init__(self):
        super().__init__()
        self._api_status_token = None
        self._pellet_delivery_status = 0
        self._pellet_history = 0

    def process_frames(self, all_frames: list, left_frames: list, right_frames: list):
        if self._star_part_index == -1 or self._pellet_part_index == -1:
            return (0, 0, 0, 0), (0, 0, 0, 0)

        locs_l, locs_r = super(PelletOnlyPoseAlgorithm, self).process_frames(all_frames, left_frames, right_frames)

        pellet_seen = False

        for pose in all_frames:
            pellet_seen = pose[self._pellet_part_index, 2] >= 0.9
            if pellet_seen:
                break

        if self._api_status_token is None:
            if pellet_seen:
                self._pellet_history = 0
            else:
                self._pellet_history += 1
            if self._pellet_delivery_status == 3:
                self._pellet_delivery_status = 0
                self._pellet_history = 0
            elif self._pellet_delivery_status == 2:
                self._api_status_token = self.api.release_pellet()
                self._pellet_delivery_status = 3
            elif self._pellet_delivery_status == 1:
                self._api_status_token = self.api.send_pellet()
                self._pellet_delivery_status = 2
            elif self._pellet_delivery_status == 0:
                if self._pellet_history >= 10:
                    self._api_status_token = self.api.load_pellet()
                    self._pellet_delivery_status = 1

        return locs_l, locs_r

    def api_response(self, token: object, success: bool):
        if token == self._api_status_token:
            self._api_status_token = None
