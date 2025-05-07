import typing
from collections import namedtuple
from dataclasses import dataclass

import numpy

from autotrainer.core import ObservableObject

PoseTuple = namedtuple("PoseTuple", ["x", "y"])


@dataclass(frozen=True)
class PoseLocation:
    name: str
    index: int
    x: float
    y: float


@dataclass(frozen=True)
class PoseResponse:
    sequence: int
    """Simple index to track responses"""

    parts_flags: (typing.Dict[str, bool], typing.Dict[str, bool], typing.Dict[str, bool])
    """Tuple indicating part seen for left, right, and both (same frame)"""

    locations: typing.List[typing.List[PoseLocation]]
    """Normalized X, Y locations for each part for each camera, if above threshold, otherwise -1, -1"""

    def x_y_1(self) -> typing.List[PoseTuple]:
        """Ugly name for the x, y coordinates of the first camera"""
        return list(map(lambda p: (p.x, p.y), self.locations[0]))

    def x_y_2(self) -> typing.List[PoseTuple]:
        """Ugly name for the x, y coordinates of the second camera"""
        return list(map(lambda p: (p.x, p.y), self.locations[1]))

    @property
    def pellet_seen(self) -> bool:
        """Default logic/conditions for pellet seen"""
        return self.parts_flags[0]["Pellet"] or self.parts_flags[1]["Pellet"]

    @property
    def star_seen(self):
        """Default logic/conditions for star seen"""
        return self.parts_flags[0]["Star"] or self.parts_flags[1]["Star"]

    @property
    def mouse_seen(self) -> bool:
        """Default logic/conditions for mouse seen"""
        return self.parts_flags[2]["Nose"]


class PoseAlgorithm(ObservableObject):
    """
    The PoseAlgorithm is the autotrainer-specific interpretation of the output from a pose model.

    A pose model implementation will return frames of data containing parts with their locations and confidence values.
    The PoseAlgorithm determines interpreted values such as whether a part has been "seen" (e.g., above some confidence
    threshold), or may map locations to a normalized coordinate system.

    The objective is for applications and scripts to not have to know low-level part names as used by the model, how
    thresholds are applied and similar (though they may want to be able to set or modify those thresholds).

    The PoseResponse returned by the PoseAlgorithm captures the interpreted values (e.g., "mouse seen" which may be
    some function of multiple parts being present and/or at different confidence levels).
    """
    # TODO Configurable properties
    MIN_CONFIDENCE_PLOT_THRESHOLD = 0.9
    MIN_CONFIDENCE_PRESENT_THRESHOLD = 0.9

    def __init__(self):
        super().__init__(event_names=("pose_changed",))

        self._parts_list = list()
        self._parts = dict()
        self._expected_num_parts = 0
        self._sequence = 0

        self._default_parts_flag = dict()
        self._default_locations = list()

    @property
    def part_names(self) -> list:
        return list(self._parts_list)

    @property
    def part_count(self) -> int:
        return len(self._parts_list)

    def get_part_index(self, part: str) -> int:
        if part in self._parts:
            return self._parts[part]
        return -1

    def initialize(self, parts: list):
        """
        Will be called once after the model initialized and body parts properties have been set.
        See part_names() and get_part_index(name).
        """
        self._parts_list = list(parts)
        self._parts = dict()
        self._default_parts_flag = dict()
        self._default_locations = list()

        for idx, part in enumerate(parts):
            self._parts[part] = idx
            self._default_parts_flag[part] = False
            self._default_locations.append(None)

        self._expected_num_parts = len(self._parts_list)

    def process(self, all_frames: typing.List[numpy.ndarray]) -> PoseResponse:
        """
        Process the frames from the pose model and return a PoseResponse.
        Args:
            all_frames: and interleaved list of pose frame data from the left and right cameras.
        Returns:
            PoseResponse: a PoseResponse object with the processed data
        """
        left_frames = list()
        right_frames = list()

        for frame in range(0, len(all_frames), 2):
            left_frames.append(all_frames[frame])

        for frame in range(1, len(all_frames), 2):
            right_frames.append(all_frames[frame])

        return self.process_frames(all_frames, left_frames, right_frames)

    def process_frames(self, all_frames: list, left_frames: list, right_frames: list) -> PoseResponse:
        """
        Optional function to process frames with the left and right camera frame results separated.  Each frame is
        already reshaped to (num_body_parts, 3).

        Args:
            all_frames - frames in order as output from DLC
            left_frames - sorted for just the left
            right_frames - sorted for just the right

        Returns:
            PoseResponse: a PoseResponse object with the processed data
        """
        self._sequence += 1

        locations_1 = self._find_parts(left_frames)
        locations_2 = self._find_parts(right_frames)

        parts_flag_1 = dict(self._default_parts_flag)
        parts_flag_2 = dict(self._default_parts_flag)
        parts_flag_3 = dict(self._default_parts_flag)

        for pose_l, pose_r in zip(left_frames, right_frames):
            for idx, part in enumerate(self._parts_list):
                maybe_dual = False
                if pose_l[idx, 2] >= PoseAlgorithm.MIN_CONFIDENCE_PRESENT_THRESHOLD:
                    parts_flag_1[part] = True
                    maybe_dual = True
                if pose_r[idx, 2] >= PoseAlgorithm.MIN_CONFIDENCE_PRESENT_THRESHOLD:
                    parts_flag_2[part] = True
                    if maybe_dual:
                        parts_flag_3[part] = True

        response = PoseResponse(sequence=self._sequence, parts_flags=(parts_flag_1, parts_flag_2, parts_flag_3),
                                locations=[locations_1, locations_2])

        self.pose_changed(response)

        return response

    def _find_parts(self, frames: list) -> typing.List[PoseLocation]:
        locations: typing.List[PoseLocation] = list(self._default_locations)

        for pose in frames:
            for idx, part in enumerate(self._parts_list):
                if pose[idx, 2] >= PoseAlgorithm.MIN_CONFIDENCE_PLOT_THRESHOLD:
                    locations[idx] = (PoseLocation(part, idx, pose[idx, 0], pose[idx, 1]))
                elif locations[idx] is None:
                    locations[idx] = (PoseLocation(part, idx, -1, -1))

        return locations
