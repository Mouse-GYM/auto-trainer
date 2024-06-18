import numpy

from .pose_response_api import PoseResponseApi


class PoseAlgorithm:
    def __init__(self):
        self._parts = dict()
        self._api = None
        self._expected_num_parts = -1

    @property
    def part_names(self) -> list:
        return list(self._parts.keys())

    @property
    def api(self) -> PoseResponseApi:
        return self._api

    @api.setter
    def api(self, api: PoseResponseApi):
        self._api = api

    def get_part_index(self, part: str) -> int:
        if part in self._parts:
            return self._parts[part]
        return -1

    def set_parts(self, parts: list):
        for idx, part in enumerate(parts):
            self._parts[part] = idx

        self._expected_num_parts = len(self._parts)

    '''
    Will be called once after the model initialized and body parts properties have been set.
    See part_names() and get_part_index(name)
    '''

    def initialize(self):
        pass

    def process(self, pose_data: numpy.ndarray):
        all_frames = list()

        for frame in range(pose_data.shape[0]):
            all_frames.append(pose_data[frame, :].reshape(self._expected_num_parts, 3))

        left_frames = list()
        right_frames = list()

        for frame in range(0, len(all_frames), 2):
            left_frames.append(all_frames[frame])

        for frame in range(1, len(all_frames), 2):
            right_frames.append(all_frames[frame])

        return self.process_frames(all_frames, left_frames, right_frames)

    '''
    all_frames - frames in order as output from DLC
    left_frames - sorted for just the left
    right_frames - sorted for just the right
    Each frame is already reshaped to (num_body_parts, 3)
    '''

    def process_frames(self, all_frames: list, left_frames: list, right_frames: list):
        # API supports these commands.
        # self.api.move_home()
        # self.api.load_pellet()
        # self.api.send_pellet()
        # self.api.release_pellet()
        # Can return up to two locations per camera to be shown on the live feed
        pass

    def api_response(self, token: object, success: bool):
        # The token is an opaque object.  Should just use with != or == to determine if it one you are waiting for.
        # If we get our token back, the move is done.  Clear our flag.
        pass

    def terminate(self):
        pass
