import dataclasses
import math
import operator
from typing import List, Dict, Optional, Tuple, Callable
from collections import namedtuple, defaultdict
from dataclasses import dataclass

import numpy
import pandas

from autotrainer.core import ObservableObject, Pairs3dOffsetT, Offset3DTuple
from autotrainer.core.logging import get_verbose_logger
from .config import StereoParams
from autotrainer.inference.pose_elements import SceneElement

# see inline where imported:
# from autotrainer.behavior.analysis.calibration import triangulate_3d_with_params
# import loop/cycle atm


logger = get_verbose_logger(__name__)


PoseTuple = namedtuple("PoseTuple", ["x", "y"])


@dataclass(frozen=True)
class PoseLocation:
    name: str
    index: int
    x: float
    y: float


@dataclass(frozen=True)
class PoseResponse:
    """Defines response of various input"""

    sequence: int
    """Simple index to track responses"""

    parts_flags: Tuple[
        Dict[str, bool],
        Dict[str, bool],
        Dict[str, bool],
    ]
    """Tuple indicating part seen for left, right, and both (same frame)"""

    locations: List[Dict[SceneElement, PoseLocation]]
    """X, Y locations for each part for each camera, if above threshold, otherwise -1, -1 (or not present)"""

    parts_3d_offsets: Dict[str, Dict[str, Offset3DTuple]] = dataclasses.field(default_factory=dict)
    """3D offsets of the pairs of parts requested during the response creation"""

    @property
    def pellet_seen(self) -> bool:
        """Default logic/conditions for pellet seen"""
        return self.parts_flags[0][SceneElement.Pellet] or self.parts_flags[1][SceneElement.Pellet]

    @property
    def star_seen(self):
        """Default logic/conditions for star seen"""
        return self.parts_flags[0][SceneElement.Star] or self.parts_flags[1][SceneElement.Star]

    @property
    def mouse_seen(self) -> bool:
        """Default logic/conditions for mouse seen: require seen in ALL/both cams"""
        # return all(flags.get(SceneElement.Nose, False) for flags in self.parts_flags)
        return self.parts_flags[2][SceneElement.Nose]

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
            value = self.parts_flags[idx].get(part, None)
            if value is not None:
                if value:
                    return True
        return False

    def get_parts_3d_offset(
        self,
        part1: str,
        part2: str,
        *,
        require_present_all_cams: bool = True,
    ) -> Optional[Offset3DTuple]:
        """Return the 3d offsets between part1 and part2,
        if none exist/is available return None instead
        """
        part1 = SceneElement(part1).value
        part2 = SceneElement(part2).value
        # -1 means all cams in is_part_seen(), while no idx means any cam:
        cams_idx = (-1,) if require_present_all_cams else ()
        part1_seen = self.is_part_seen(part1, cams_idx=cams_idx)
        part2_seen = self.is_part_seen(part2, cams_idx=cams_idx)
        if not part1_seen or not part2_seen:
            return None
        value = self.parts_3d_offsets.get(part1, {}).get(part2, None)
        if value is None:
            value = self.parts_3d_offsets.get(part2, {}).get(part1, None)
            if value is None:
                return None
            value = tuple(map(operator.neg, value))
        return Offset3DTuple(value)


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
        self._parts_list: List[SceneElement] = []
        self._parts: Dict[SceneElement, int] = {}  # key is part name, value is part model index
        self._expected_num_parts = 0
        self._sequence = 0
        self._default_parts_flag: Dict[str, bool] = {}
        self._default_locations = []
        self._pose_result_columns: Optional[pandas.MultiIndex] = None
        self._has_hands_part_names: bool = False
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
            SceneElement(part)
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
        self._has_hands_part_names = all(
            col in parts
            for col in ('RH_flat', 'RH_spread', 'RH_grab', 'LH_flat', 'LH_spread', 'LH_grab')
        )

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

        frames_per_cam = len(left_frames)

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

        # NB: only handling/using last frame of batch (for each cam):
        # we could eventually do all the frames and eventually make an avg ?
        cams_last_frame = [cam_frames[-1] for cam_frames in per_cam_frames]
        parts_3d_offsets = defaultdict(dict)
        if len(pairs_3d_offsets) > 0:
            df_3d = self._handle_offsets_pose_data(*([frame] for frame in cams_last_frame))
            for part1, part2 in pairs_3d_offsets:
                parts_3d_offsets[part1][part2] = tuple(
                      df_3d[part1].iloc[-1, 0:3]  # last frame, 3 first columns (x, y, z)
                    - df_3d[part2].iloc[-1, 0:3]
                )
                # check of parts confidence level is handled in PoseResponse.get_parts_3d_offset()

        if self._has_hands_part_names:
            # given import loop/cycle issue to be fixed:
            from autotrainer.behavior.analysis.prepare_jetson_data import process_hand_data

            # todo: should be somehow more global:
            hand_base_names = ['H_flat', 'H_spread', 'H_grab']
            hand_options = ['R', 'L']
            bodyparts = ['R_Hand', 'L_Hand']
            coordinates = ['x', 'y', 'likelihood']
            columns = pandas.MultiIndex.from_product([bodyparts, coordinates], names=['bodyparts', 'coordinates'])
            df = pandas.DataFrame(
                numpy.concatenate(cams_last_frame).reshape(2  # nbr of frames in the dataframe
                                                           , -1),
                columns=self._pose_result_columns)
            process_hands_results = pandas.DataFrame(columns=columns, index=range(2))
            process_hands_results = process_hand_data(
                df,
                hand_base_names=hand_base_names,
                hand_options=hand_options,
                dlc_seg="_raw2D",
                newdf=process_hands_results
            )
            for elem in SceneElement.L_Hand, SceneElement.R_Hand:
                if __debug__ and elem not in process_hands_results:
                    continue
                v = process_hands_results[elem]
                if v['likelihood'][0] > self.MIN_CONFIDENCE_PRESENT_THRESHOLD:
                    locations_1[elem] = PoseLocation(elem, -1, v['x'][0], v['y'][0])
                if v['likelihood'][1] > self.MIN_CONFIDENCE_PRESENT_THRESHOLD:
                    locations_2[elem] = PoseLocation(elem, -1, v['x'][1], v['y'][1])

        response = PoseResponse(
            sequence=self._sequence,
            parts_flags=(parts_flag_1, parts_flag_2, parts_flag_3),
            locations=[locations_1, locations_2],
            parts_3d_offsets=dict(parts_3d_offsets),
        )
        self.pose_changed(response)
        return response

    def _find_parts(self, frames: list) -> Dict[SceneElement, PoseLocation]:
        locations: Dict[SceneElement, PoseLocation] = {}
        for pose in frames:
            for idx, part in enumerate(self._parts_list):
                if pose[idx, 2] >= PoseAlgorithm.MIN_CONFIDENCE_PLOT_THRESHOLD:
                    locations[part] = PoseLocation(part, idx, pose[idx, 0], pose[idx, 1])
        return locations
