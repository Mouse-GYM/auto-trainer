import dataclasses
import itertools
import math
import operator
from typing import List, Dict, Optional, Tuple, Literal
from collections import namedtuple, defaultdict
from dataclasses import dataclass

import numpy
import pandas

from autotrainer.core import ObservableObject, Pairs3dOffsetT, Offset3DTuple, get_perf_now
from autotrainer.inference.calibration import triangulate_3d_with_params
from autotrainer.core.logging import get_verbose_logger
from autotrainer.inference.config import StereoParams
from autotrainer.core.pose_elements import SceneElement, AllHandsParts

from autotrainer.inference.analysis.prepare_jetson_data import process_hand_data, reorient_and_center_step1


logger = get_verbose_logger(__name__)


PoseTuple = namedtuple("PoseTuple", ["x", "y"])


@dataclass(frozen=True)
class PoseLocation:
    index: int
    x: float
    y: float

    def __repr__(self):
        return f"PoseLocation(index={self.index}, x={self.x:.2f}, y={self.y:.2f})"


@dataclass(frozen=True)
class PoseResponse:
    """Defines response of various input"""

    sequence: int = 0
    """Simple index to track responses"""

    perf_c: float = dataclasses.field(default_factory=get_perf_now)
    """Perf counter when this response applies"""

    parts_flags: Tuple[
        Dict[str, bool],
        Dict[str, bool],
        Dict[str, bool],
    ] = dataclasses.field(default_factory=lambda: ({}, {}, {}))
    """Tuple indicating part seen for left, right, and both (same frame)"""

    locations: List[Dict[str, PoseLocation]] = dataclasses.field(default_factory=list)
    """X, Y locations for each part for each camera, if above threshold, otherwise -1, -1 (or not present)"""

    parts_3d_offsets: Dict[str, Dict[str, Offset3DTuple]] = dataclasses.field(default_factory=dict)
    """3D offsets of the pairs of parts requested during the response creation"""

    locations_3d: Dict[str, Offset3DTuple] = dataclasses.field(default_factory=dict)
    """3D locations of the monitored parts/elements"""

    raw_loc_3d: Dict[str, Offset3DTuple] = dataclasses.field(default_factory=dict)

    @property
    def pellet_seen(self) -> bool:
        """Default logic/conditions for pellet seen"""
        return self.parts_flags[0].get(SceneElement.Pellet, False) or self.parts_flags[1].get(SceneElement.Pellet, False)

    @property
    def star_seen(self):
        """Default logic/conditions for star seen"""
        return self.parts_flags[0].get(SceneElement.Star, False) or self.parts_flags[1].get(SceneElement.Star, False)

    @property
    def mouse_seen(self) -> bool:
        """Default logic/conditions for mouse seen: require seen in ALL/both cams"""
        # return all(flags.get(SceneElement.Nose, False) for flags in self.parts_flags)
        return self.parts_flags[2].get(SceneElement.Nose, False)

    @property
    def diamond_seen(self):
        p_flags = self.parts_flags
        return p_flags[0].get(SceneElement.Diamond, False) or p_flags[1].get(SceneElement.Diamond, False)

    @property
    def triangle_seen(self):
        p_flags = self.parts_flags
        return p_flags[0].get(SceneElement.Triangle, False) or p_flags[1].get(SceneElement.Triangle, False)

    @property
    def lh_grab_seen(self):
        return self.is_part_seen(SceneElement.LH_grab)  # both cams

    @property
    def rh_grab_seen(self):
        return self.is_part_seen(SceneElement.RH_grab)  # both cams

    def is_part_seen(self, part: str, *, cams_idx: Tuple[int, ...] = ()):
        """Check whether `part` is seen or not in cams_idx, if cams_idx empty: check all"""
        if len(cams_idx) == 0:
            # last part flags is conjunction of all previous cams
            cams_idx = [-1]
        return all(
            self.parts_flags[idx].get(part, None)
            for idx in cams_idx
        )

    def get_parts_3d_offset(
        self,
        part1: str,
        part2: str,
    ) -> Optional[Offset3DTuple]:
        """Return the 3d offsets between part1 and part2, relatively to part1,
        i.e: returns loc3d[part2] - loc3d[part1]
        if none exist/is available return None instead
        """
        value = self.parts_3d_offsets.get(part1, {}).get(part2, None)
        if value is None:
            value = self.parts_3d_offsets.get(part2, {}).get(part1, None)
            if value is None:
                return None
            logger.debug("get_parts_3d_offset(%r, %r): detected reversed offsets 3d, "
                         "you shall switch your pair key.",
                         part1, part2)
            value = tuple(map(operator.neg, value))
        return Offset3DTuple(value)


class PoseAlgorithm:
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

    process_frames_select_frames_method: Literal['all_most_likely', 'last_one'] = "all_most_likely"

    def __init__(
        self,
        *,
        stereo_params: Optional[StereoParams] = None,
        calib_metadata: Optional[Dict] = None,
        cam_names: Optional[List[str]] = None,
        square_size: Optional[int] = None,
        cam_offsets: Optional[List[float]] = None,
    ):
        super().__init__()
        self._parts_list: List[str] = []
        self._parts: Dict[str, int] = {}  # key is part name, value is part model index
        self._sequence = 0
        self._default_parts_flag: Dict[str, bool] = {}
        self._default_locations = []
        self._pose_result_columns: Optional[pandas.MultiIndex] = None
        self._has_hands_part_names: bool = False
        self._stereo_params = stereo_params
        self._calib_metadata = calib_metadata
        self._cam_names = cam_names
        self._square_size = square_size
        self._cam_offsets = cam_offsets
        #
        axis_labels = ['x', 'y', 'likelihood']
        self._hand_base_names = ['H_flat', 'H_spread', 'H_grab']
        self._hand_options = ['R', 'L']
        self._hands_columns = pandas.MultiIndex.from_product([
            [SceneElement.R_Hand, SceneElement.L_Hand], axis_labels],
            names=['bodyparts', 'coordinates'])
        self._hands_input_parts = list(AllHandsParts)
        self._hands_input_columns = pandas.MultiIndex.from_product(
            [self._hands_input_parts, axis_labels], names=['bodyparts', 'coordinates']
        )
        #
        self._measure_offset_parts = [
            SceneElement.Star,
            SceneElement.Triangle,
            SceneElement.Diamond,
            SceneElement.Pellet,
            # also include all hands parts:
            *self._hands_input_parts,
        ]
        self._measure_offset_parts_columns = pandas.MultiIndex.from_product(
            [self._measure_offset_parts, axis_labels],
            names=["bodyparts", "coords"]
        )

    @property
    def stereo_params(self):
        return self._stereo_params

    @property
    def calib_metadata(self):
        return self._calib_metadata

    @property
    def square_size(self):
        return self._square_size

    @property
    def cam_names(self):
        return self._cam_names

    @property
    def cam_offsets(self):
        return self._cam_offsets

    @property
    def part_names(self) -> list:
        return list(self._parts_list)

    @property
    def part_count(self) -> int:
        return len(self._parts_list)

    def get_part_index(self, part: str) -> int:
        """Give the model part index, or -1 if unknown"""
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
        logger.info("Initializing with parts: %s", parts)
        parts = self._parts_list[:] = [
            SceneElement(part)  # this is not exactly required anymore,
            # but only ensure the given part will be cached within SceneElement cached items list/dict.
            for part in parts
        ]
        self._parts.clear()
        self._default_parts_flag.clear()
        self._default_locations.clear()

        for idx, part in enumerate(parts):
            self._parts[part] = idx
            self._default_parts_flag[part] = False
            self._default_locations.append(None)

        axis_labels = ("x", "y", "likelihood")
        columns = pandas.MultiIndex.from_product([self._parts_list, axis_labels],
                                                 names=["bodyparts", "coords"])
        self._pose_result_columns = columns
        self._has_hands_part_names = all(map(parts.__contains__, (
            SceneElement.RH_flat, SceneElement.RH_spread, SceneElement.RH_grab,
            SceneElement.LH_flat, SceneElement.LH_spread, SceneElement.LH_grab,
        )))

    @property
    def pose_result_columns(self) -> pandas.MultiIndex:
        return self._pose_result_columns

    def _handle_offsets_pose_data(self,
        *per_cam_detection: numpy.ndarray
    ):
        """Handle pose data offsets"""
        stereo_params = self._stereo_params
        if stereo_params is None:
            raise RuntimeError("stereo_params must be set with a valid calib src dir")
        p_thresh = 0.9  # confidence threshold for DLC raw output
        min_cluster = 10  # maximum allowed interpolation
        # not sure min_cluster change anything for when nbr frames == 1 (per cam)
        #
        frames_per_cam = len(per_cam_detection[0])
        #
        # reshape then sort by confidence/likelihood and takes most likely:
        df0_2d = pandas.DataFrame(per_cam_detection[0].reshape(frames_per_cam, -1), columns=self._measure_offset_parts_columns)
        if frames_per_cam > 1:
            df0_2d = df0_2d.sort_index(level="likelihood", ascending=False).reset_index(drop=True).iloc[0:1]
        df1_2d = pandas.DataFrame(per_cam_detection[1].reshape(frames_per_cam, -1), columns=self._measure_offset_parts_columns)
        if frames_per_cam > 1:
            df1_2d = df1_2d.sort_index(level="likelihood", ascending=False).reset_index(drop=True).iloc[0:1]
        #
        df_2d = pandas.DataFrame(
            numpy.concatenate([df0_2d.values, df1_2d.values]),
            columns=self._measure_offset_parts_columns,
        )
        # df_2d = interpolate_coordinates(df_2d, p_thresh)  # not required probably
        df_3d = triangulate_3d_with_params(
            [df_2d.iloc[0:1], df_2d.iloc[1:2]],
            body_parts=self._measure_offset_parts,
            stereo_params=self._stereo_params,
            p_thresh=p_thresh,
            min_cluster=min_cluster,
        )
        raw_df_3d = df_3d
        # but reorient and center looks required:
        center_method = (1, SceneElement.Diamond)
        df_3d = reorient_and_center_step1(
            df_3d=df_3d,
            stereo_file=stereo_params.as_pickle_dict(),
            center_method=center_method,
            frame_rate=150,  # could be todo: allow configure/set from camera fps itself
            bpts=self._measure_offset_parts,
            calib_metadata=self._calib_metadata,
            cam_names=self._cam_names,
            cam_offsets=self._cam_offsets,
            square_size=self._square_size,
            save_offsets=False,
            src_dir="/dev/null",
        )
        return raw_df_3d, df_3d

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

        return self.process_frames(left_frames, right_frames,
                                   pairs_3d_offsets=pairs_3d_offsets)

    def process_frames(
        self,
        *per_cam_frames: List[numpy.ndarray],
        pairs_3d_offsets: Pairs3dOffsetT,
    ) -> PoseResponse:
        """
        Function to process frames with all cameras frame results separated. Each frame is
        already reshaped to (num_body_parts, 3).
        Args:
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

        # get parts presence:
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

        if self.process_frames_select_frames_method == "last_one":
            cams_last_frame = [[cam_frames[-1]] for cam_frames in per_cam_frames]
            selected_cams_frames = cams_last_frame
        else:
            assert self.process_frames_select_frames_method == "all_most_likely"
            selected_cams_frames = per_cam_frames

        gpi = self.get_part_index
        #
        if self._has_hands_part_names:
            # compute L_Hand / R_Hand averaged position (based on possibly many sub-hand parts)
            all_lst = [
                [f[gpi(p)] for p in self._hands_input_parts]
                for f in itertools.chain(*selected_cams_frames)
            ]
            all_frames = numpy.asarray(all_lst).reshape(len(all_lst), -1)
            df = pandas.DataFrame(
                all_frames,
                columns=self._hands_input_columns)
            process_hands_results = pandas.DataFrame(columns=self._hands_columns, index=range(len(df)))
            process_hands_results = process_hand_data(
                df,
                hand_base_names=self._hand_base_names,
                hand_options=self._hand_options,
                dlc_seg="_raw2D",
                newdf=process_hands_results,
                additional_names=[],
            )
            assert len(process_hands_results) == len(df)
            v0_raw = process_hands_results.iloc[0:len(selected_cams_frames[0])]
            v1_raw = process_hands_results.iloc[len(selected_cams_frames[0]):]
            for elem in SceneElement.L_Hand, SceneElement.R_Hand:
                if __debug__ and elem not in process_hands_results.columns:
                    logger.warning("%s not present in hands results", elem)
                    continue
                # uses last(most recent) one:
                if self.process_frames_select_frames_method == "last_one":
                    v0 = v0_raw[elem].iloc[-1]
                    v1 = v1_raw[elem].iloc[-1]
                else:
                    # but if want uses most likelihood, then:
                    v0 = v0_raw[elem].sort_values(by="likelihood", ascending=False).reset_index().iloc[0]
                    v1 = v1_raw[elem].sort_values(by="likelihood", ascending=False).reset_index().iloc[0]
                if v0['likelihood'] >= self.MIN_CONFIDENCE_PRESENT_THRESHOLD:
                    locations_1[elem] = PoseLocation(-1, v0['x'], v0['y'])
                if v1['likelihood'] >= self.MIN_CONFIDENCE_PRESENT_THRESHOLD:
                    locations_2[elem] = PoseLocation(-1, v1['x'], v1['y'])

        locations_3d = {}
        raw_3d = {}
        parts_3d_offsets = defaultdict(dict)
        if len(pairs_3d_offsets) > 0:
            raw_df_3d, df_3d = self._handle_offsets_pose_data(*(
                numpy.asarray([
                    [frame[gpi(p)] for p in self._measure_offset_parts]
                    for frame in frames
                ])
                for frames in selected_cams_frames
            ))
            for part1, part2 in pairs_3d_offsets:
                if parts_flag_3.get(part1):
                    raw_3d[part1] = Offset3DTuple(raw_df_3d[part1].iloc[-1, 0:3])
                    loc1 = locations_3d[part1] = Offset3DTuple(
                        df_3d[part1].iloc[-1, 0:3])  # last frame, 3 first columns (x, y, z)
                else:
                    loc1 = None
                if parts_flag_3.get(part2):
                    raw_3d[part2] = Offset3DTuple(raw_df_3d[part2].iloc[-1, 0:3])
                    loc2 = locations_3d[part2] = Offset3DTuple(df_3d[part2].iloc[-1, 0:3])
                    if loc1 is not None:
                        parts_3d_offsets[part1][part2] = tuple(loc2 - loc1)

        response = PoseResponse(
            sequence=self._sequence,
            parts_flags=(parts_flag_1, parts_flag_2, parts_flag_3),
            locations=[locations_1, locations_2],
            parts_3d_offsets=dict(parts_3d_offsets),
            locations_3d=locations_3d,
            raw_loc_3d=raw_3d,
        )
        return response

    def _find_parts(self, frames: List[numpy.ndarray]) -> Dict[str, PoseLocation]:
        locations: Dict[str, PoseLocation] = {}
        for pose in frames:
            for idx, part in enumerate(self._parts_list):
                if pose[idx, 2] >= PoseAlgorithm.MIN_CONFIDENCE_PLOT_THRESHOLD:
                    locations[part] = PoseLocation(idx, pose[idx, 0], pose[idx, 1])
        return locations
