import logging
import time

from autotrainer.inference.pose_algorithms import register
from inference_algorithms.marker_only_pose_algorithm import MarkerOnlyPoseAlgorithm

logger = logging.getLogger(__name__)

PELLET_MISSING_TIME = 1


@register("Pellet Only")
class PelletOnlyPoseAlgorithm(MarkerOnlyPoseAlgorithm):
    def __init__(self):
        super().__init__()
        self._api_status_token = None
        self._pellet_delivery_status = 0
        self._pellet_missing = time.time()

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
                self._pellet_missing = time.time()

            if self._pellet_delivery_status == 3:
                logger.debug("delivery cycle complete")
                self._pellet_missing = time.time()
                logger.debug(f"last seen set to: {self._pellet_missing}")
                self._pellet_delivery_status = 0
                # self._pellet_history = 0
            elif self._pellet_delivery_status == 2:
                self._api_status_token = self.api.release_pellet()
                logger.debug(f"release: waiting for api token: {self._api_status_token}")
                self._pellet_delivery_status = 3
            elif self._pellet_delivery_status == 1:
                self._api_status_token = self.api.send_pellet()
                logger.debug(f"send: waiting for api token: {self._api_status_token}")
                self._pellet_delivery_status = 2
            elif self._pellet_delivery_status == 0:
                if time.time() - self._pellet_missing >= PELLET_MISSING_TIME:
                    self._api_status_token = self.api.load_pellet()
                    logger.debug(f"load: waiting for api token: {self._api_status_token}")
                    self._pellet_delivery_status = 1

        return locs_l, locs_r

    def api_response(self, token: object, success: bool):
        if token == self._api_status_token:
            logger.debug(f"pending api token received: {token}")
            self._api_status_token = None
        else:
            logger.debug(f"unexpected api token received: {token}")
