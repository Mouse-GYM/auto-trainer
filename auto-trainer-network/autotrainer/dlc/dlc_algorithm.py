import numpy

from autotrainer.pose_response_api import PoseResponseApi


class DLCAlgorithm:
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
        return self._parts[part]

    def set_parts(self, parts: list):
        for idx, part in enumerate(parts):
            self._parts[part] = idx

        self._expected_num_parts = len(self._parts)

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

    def process_frames(self, all_frames: list, left_frames: list, right_frames: list):
        pass

    def api_response(self, token: object, success: bool):
        pass

    def terminate(self):
        pass
