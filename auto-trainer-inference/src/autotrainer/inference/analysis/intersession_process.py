import os
from pathlib import Path
from typing import Optional, Tuple

import numpy

from autotrainer.core import ProjectInfo, video_write_ext
from autotrainer.core.diamond_triangle_config import DiamondTriangleOffsetConfig
from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.pose_elements import SceneElement

from autotrainer.core.configuration import DEFAULT_3D_CALIB_DIR_NAME

from autotrainer.inference.analysis.prepare_jetson_data import process_raw_data
from autotrainer.inference.analysis.parse_pellet_presentations_jetson import segment_reaches

from . import IntersessionResponse

logger = get_verbose_logger(__name__)


AvailableShiftXYZ = numpy.array([[-5, 5], [-5, 5], [-5, 5]])


_segment_reach_debug: int = int(os.getenv("AUTOTRAINER_SEGMENT_REACH_DEBUG", 0))


def intersession_process(
    project: ProjectInfo,
    *,
    calib_dir: Optional[Path] = None,
    axis_flips: Tuple[int, int, int] = DiamondTriangleOffsetConfig.flips_inference_diamond,
    debug_level: int = _segment_reach_debug,
) -> IntersessionResponse:
    """
    Called after pose processing for intersession analysis.

    :param project: current project info for finding/defining file names
    :param calib_dir: calibration directory if not default.
    :param debug_level: integer debug level.
    :return: information required to update behavior for future sessions
    """
    location, _, _ = project.get_session_path()
    logger.info("process intersession pose data using %s", location)
    calib_src_dir = (
        Path(f"~/Autotrainer/{DEFAULT_3D_CALIB_DIR_NAME}") if calib_dir is None else calib_dir
    ).expanduser()
    if not calib_src_dir.is_dir():
        logger.warning("calib_src_dir %s is not a directory",  calib_src_dir)
    calib_src_dir = calib_src_dir.as_posix()
    vid_tag = "." + video_write_ext
    dlc_seg = "_raw2D"
    center_method = (1, SceneElement.Diamond)
    #
    df_lr, centered_df_3d = process_raw_data(location, vid_tag, dlc_seg, calib_src_dir, center_method)
    #
    # apply flips to get axis values in desired order before proceeding to segment reaches after:
    #for elem in centered_df_3d.columns.get_level_values(0).unique():
    #    for axis, axis_flip in zip("xyz", axis_flips):
    #        centered_df_3d[(elem, axis)] *= axis_flip
    #
    results_dict = segment_reaches(
        session=location,
        center_method=center_method,
        df_lr=df_lr,
        df_3d=centered_df_3d,
        debug=debug_level,
    )
    logger.verbose("process intersession pose data complete %s", results_dict)
    return IntersessionResponse(
        rh_max_vp_list=results_dict['rh_max_vp_list'],
        food_consumed=results_dict['pellets_consumed'],
        successful_reaches=results_dict['successful_reaches'],
        pellets_presented=results_dict['pellets_presented'],
        total_reaches=results_dict['total_reaches'],
    )
