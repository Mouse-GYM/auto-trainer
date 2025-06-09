import dataclasses
import math
import operator
from typing import List, Dict, Union, Optional, Tuple, Callable
from collections import namedtuple, defaultdict
from dataclasses import dataclass

import numpy
import pandas

from autotrainer.core import ObservableObject
from autotrainer.core.logging import get_verbose_logger
from .config import StereoParams
from autotrainer.inference.pose_elements import SceneElement

# see inline where imported:
# from autotrainer.behavior.analysis.calibration import triangulate_3d_with_params
# import loop/cycle atm


logger = get_verbose_logger(__name__)


PoseTuple = namedtuple("PoseTuple", ["x", "y"])


Pairs3dOffsetT = Union[List[Tuple[str, str]], Tuple[Tuple[str, str], ...]]


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

    parts_flags: Tuple[Dict[str, bool], Dict[str, bool], Dict[str, bool]]
    """Tuple indicating part seen for left, right, and both (same frame)"""

    locations: List[List[PoseLocation]]
    """X, Y locations for each part for each camera, if above threshold, otherwise -1, -1"""

    parts_3d_offsets: Dict[str, Dict[str, Tuple[float, float, float]]] = dataclasses.field(default_factory=dict)
    """3D offsets of the pairs of parts requested during the response creation"""

    def x_y_1(self) -> List[PoseTuple]:
        """Ugly name for the x, y coordinates of the first camera"""
        return list(map(lambda p: (p.x, p.y), self.locations[0]))

    def x_y_2(self) -> List[PoseTuple]:
        """Ugly name for the x, y coordinates of the second camera"""
        return list(map(lambda p: (p.x, p.y), self.locations[1]))

    def x_y_by_idx(self, cam_idx: int) -> List[PoseTuple]:
        return list(map(lambda p: (p.x, p.y), self.locations[cam_idx]))

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

    @property
    def diamond_seen(self):
        return self.is_part_seen(SceneElement.Diamond)

    @property
    def triangle_seen(self):
        return self.is_part_seen(SceneElement.Triangle)

    @property
    def lh_grab_seen(self):
        return self.is_part_seen(SceneElement.LH_grab)

    @property
    def rh_grab_seen(self):
        return self.is_part_seen(SceneElement.RH_grab)

    def is_part_seen(self, part: str, *, cams_idx: Tuple[int, ...] = ()):
        """Check whether `part` is seen or not in cams_idx, if cams_idx empty: check all"""
        if len(cams_idx) == 0:
            # - 1 given last part flags is conjunction of all previous cams
            cams_idx = tuple(range(len(self.parts_flags) - 1))
        part = SceneElement(part).value
        for idx in cams_idx:
            if self.parts_flags[idx][part]:
                return True
        return False

    def get_parts_3d_offset(self, part1: str, part2: str) -> Tuple[float, float, float]:
        """Return the 3d offsets between part1 and part2,
        if none exist/is available return 3 NaN values instead."""
        part1 = SceneElement(part1).value
        part2 = SceneElement(part2).value
        # should use mapping from model configuration for part1/2
        if not self.is_part_seen(part1) or not self.is_part_seen(part2):
            return math.nan, math.nan, math.nan
        value = self.parts_3d_offsets.get(part1, {}).get(part2, None)
        if value is None:
            value = self.parts_3d_offsets.get(part2, {}).get(part1, None)
            if value is None:
                return math.nan, math.nan, math.nan
            value = tuple(map(operator.neg, value))
        return value


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

    # for type hinting
    pose_changed: Callable[[PoseResponse], None]

    def __init__(
        self,
        *,
        stereo_params: Optional[StereoParams] = None,
    ):
        super().__init__(event_names=("pose_changed",))
        self._parts_list: List[str] = []
        self._parts: Dict[str, int] = {}  # key is part name, value is part model index
        self._expected_num_parts = 0
        self._sequence = 0
        self._default_parts_flag: Dict[str, bool] = {}
        self._default_locations = []
        self._pose_result_columns: Optional[pandas.MultiIndex] = None
        self._stereo_params = stereo_params

    @property
    def part_names(self) -> list:
        return list(self._parts_list)

    @property
    def part_count(self) -> int:
        return len(self._parts_list)

    def get_part_index(self, part: str) -> int:
        """Give the model part index, or -1 if unknown"""
        part = SceneElement(part).value  # sanitize
        return self._parts.get(part, -1)

    def initialize(
        self,
        parts: List[str],
        # *,  # not sure yet for:
        # map_model_2_scene_element: Optional[Dict[str, str]] = None,
    ):
        """
        Will be called once after the model initialized and body parts properties have been set.
        See part_names() and get_part_index(name).
        """
        parts = self._parts_list[:] = [
            SceneElement(part).value
            for part in parts
        ]
        self._parts.clear()
        self._default_parts_flag.clear()
        self._default_locations.clear()

        for idx, part in enumerate(parts):
            self._parts[part] = idx
            self._default_parts_flag[part] = False
            self._default_locations.append(None)

        self._expected_num_parts = len(self._parts_list)
        axis_labels = ("x", "y", "likelihood")
        columns = pandas.MultiIndex.from_product([self._parts_list, axis_labels],
                                                 names=["bodyparts", "coords"])
        self._pose_result_columns = columns

    @property
    def pose_result_columns(self) -> pandas.MultiIndex:
        return self._pose_result_columns

    def _handle_offsets_pose_data(self,
        *per_cam_pose_data: List[numpy.ndarray]
    ):
        """Handle pose data offsets"""
        from autotrainer.behavior.analysis.calibration import triangulate_3d_with_params
        # import cycle/loop, TODO: "unmix/unknot" it
        stereo_params = self._stereo_params
        if stereo_params is None:
            raise RuntimeError("stereo_params must be set with a valid calib src dir")
        p_thresh = 0.9  # confidence threshold for DLC raw output
        min_cluster = 10  # maximum allowed interpolation
        frames_per_cam = len(per_cam_pose_data[0])
        df_2d = [
            pandas.DataFrame(
                numpy.asarray(cam_pose_data).reshape(frames_per_cam, -1),
                columns=self._pose_result_columns,
            )
            for cam_pose_data in per_cam_pose_data
        ]
        df_3d = triangulate_3d_with_params(
            df_2d,
            body_parts=self._parts_list,
            stereo_params=self._stereo_params,
            p_thresh=p_thresh,
            min_cluster=min_cluster,
        )
        return df_3d

    def process(self,
        all_frames: List[numpy.ndarray],
        *,
        pairs_3d_offsets: Pairs3dOffsetT = (),
    ) -> PoseResponse:
        """
        Process the frames from the pose model and return a PoseResponse.
        Args:
            all_frames: and interleaved list of pose frame data from the left and right cameras.
            pairs_3d_offsets: List of 2-tuple pairs of parts to compute their 3d offsets.
        Returns:
            PoseResponse: a PoseResponse object with the processed data
        """
        left_frames = all_frames[0::2]
        right_frames = all_frames[1::2]

        return self.process_frames(all_frames, left_frames, right_frames,
                                   pairs_3d_offsets=pairs_3d_offsets)

    def process_frames(
        self,
        all_frames: List[numpy.ndarray],
        *per_cam_frames: List[numpy.ndarray],
        pairs_3d_offsets: Pairs3dOffsetT,
    ) -> PoseResponse:
        """
        Function to process frames with all cameras frame results separated. Each frame is
        already reshaped to (num_body_parts, 3).
        Args:
            all_frames: frames in order as output from DLC
            per_cam_frames: tuple of all frames per cam, sorted, for each cam, sorted.
            pairs_3d_offsets: List of 2-tuple pairs of parts to compute their 3d offsets.
        Returns:
            PoseResponse: a PoseResponse object with the processed data
        """
        self._sequence += 1

        left_frames = per_cam_frames[0]
        right_frames = per_cam_frames[1]

        locations_1 = self._find_parts(left_frames)
        locations_2 = self._find_parts(right_frames)

        parts_flag_1 = dict(self._default_parts_flag)
        parts_flag_2 = dict(self._default_parts_flag)
        parts_flag_3 = dict(self._default_parts_flag)

        for pose_l, pose_r in zip(left_frames, right_frames):
            for idx, part in enumerate(self._parts_list):
                if pose_l[idx, 2] >= PoseAlgorithm.MIN_CONFIDENCE_PRESENT_THRESHOLD:
                    parts_flag_1[part] = True
                    maybe_dual = True
                else:
                    maybe_dual = False
                if pose_r[idx, 2] >= PoseAlgorithm.MIN_CONFIDENCE_PRESENT_THRESHOLD:
                    parts_flag_2[part] = True
                    if maybe_dual:
                        parts_flag_3[part] = True

        parts_3d_offsets = defaultdict(dict)
        if len(pairs_3d_offsets) > 0:
            # NB: only handling last frame of batch:
            cams_last_frame = [cam_frames[-1] for cam_frames in per_cam_frames]
            df_3d = self._handle_offsets_pose_data(*([frame] for frame in cams_last_frame))
            for part1, part2 in pairs_3d_offsets:
                parts_3d_offsets[part1][part2] = tuple(
                      df_3d[part1].iloc[-1, 0:3]  # last frame, 3 first columns (x, y, z)
                    - df_3d[part2].iloc[-1, 0:3]
                )
                # check of parts confidence level is handled in PoseResponse.get_parts_3d_offset()

        response = PoseResponse(
            sequence=self._sequence,
            parts_flags=(parts_flag_1, parts_flag_2, parts_flag_3),
            locations=[locations_1, locations_2],
            parts_3d_offsets=dict(parts_3d_offsets),
        )

        self.pose_changed(response)

        return response

    def _find_parts(self, frames: list) -> List[PoseLocation]:
        locations: List[PoseLocation] = list(self._default_locations)

        for pose in frames:
            for idx, part in enumerate(self._parts_list):
                if pose[idx, 2] >= PoseAlgorithm.MIN_CONFIDENCE_PLOT_THRESHOLD:
                    locations[idx] = PoseLocation(part, idx, pose[idx, 0], pose[idx, 1])
                elif locations[idx] is None:
                    locations[idx] = PoseLocation(part, idx, -1, -1)

        return locations
