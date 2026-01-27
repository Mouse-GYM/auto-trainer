import os
from pathlib import Path
from typing import Optional

import numpy

from autotrainer.core import ProjectInfo, video_write_ext
from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.pose_elements import SceneElement

from autotrainer.core.configuration import DEFAULT_3D_CALIB_DIR_NAME

# todo: prepare_jetson_data could or should probably be moved in here/inference, given only used here..
from autotrainer.core.analysis.prepare_jetson_data import process_raw_data
from autotrainer.core.analysis.parse_pellet_presentations_jetson import segment_reaches

from . import IntersessionResponse

logger = get_verbose_logger(__name__)


AvailableShiftXYZ = numpy.array([[-5, 5], [-5, 5], [-5, 5]])


_segment_reach_debug: int = int(os.getenv("AUTOTRAINER_SEGMENT_REACH_DEBUG", 0))


def intersession_process(
    project: ProjectInfo,
    *,
    calib_dir: Optional[Path] = None,
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
    centered_df_3d = process_raw_data(location, vid_tag, dlc_seg, calib_src_dir, center_method)
    results_dict = segment_reaches(
        session=location,
        center_method=center_method,
        available_shift_xyz=AvailableShiftXYZ,
        df_3d=centered_df_3d,
        debug=debug_level,
    )
    logger.verbose("process intersession pose data complete %s", results_dict)
    return IntersessionResponse(
        pellet_x=results_dict['shift_x'],
        pellet_y=results_dict['shift_y'],
        pellet_z=results_dict['shift_z'],
        food_consumed=results_dict['pellets_consumed'],
        successful_reaches=results_dict['successful_reaches'],
        pellets_presented=results_dict['pellets_presented'],
    )
