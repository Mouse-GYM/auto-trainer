from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy

from autotrainer.core import ProjectInfo, video_write_ext
from autotrainer.core.logging import get_verbose_logger

from autotrainer.core.analysis.prepare_jetson_data import process_raw_data
from autotrainer.core.analysis.parse_pellet_presentations_jetson import segment_reaches

logger = get_verbose_logger(__name__)

available_XYZ = numpy.array([[-5, 5], [-5, 5], [-5, 5]])


@dataclass
class IntersessionResponse:
    # NB: all 3 x/y/z are relative values here:
    pellet_x: int = 0
    pellet_y: int = 0
    pellet_z: int = 0
    food_consumed: int = 0
    successful_reaches: int = 0
    pellets_presented: int = 0


def intersession_process(
    project: ProjectInfo,
    *,
    calib_dir: Optional[Path] = None,
) -> IntersessionResponse:
    """
    Called after pose processing for intersession analysis.

    :param project: current project info for finding/defining file names
    :param calib_dir: calibration directory if not default.
    :return: information required to update behavior for future sessions
    """
    # left_input = project.get_intersession_pose_path(name=project.camera_1, allow_overwrite=True)
    # right_input = project.get_intersession_pose_path(name=project.camera_2, allow_overwrite=True)
    location, _, _ = project.get_session_path()
    logger.info(f"process intersession pose data using {location}")
    calib_src_dir = Path("~/Autotrainer/4mm_6r_8c_4x").expanduser() if calib_dir is None else calib_dir
    if not calib_src_dir.is_dir():
        logger.warning("calib_src_dir %s is not a directory",  calib_src_dir)
    calib_src_dir = calib_src_dir.as_posix()
    vid_tag = "." + video_write_ext
    dlc_seg = "_raw2D"
    center_method = (1, "Pellet")
    process_raw_data(location, vid_tag, dlc_seg, calib_src_dir, center_method)
    results_dict = segment_reaches(location, center_method, available_XYZ)
    logger.success("process intersession pose data complete %s", results_dict)
    return IntersessionResponse(
        pellet_x=results_dict['shift_x'],
        pellet_y=results_dict['shift_y'],
        pellet_z=results_dict['shift_z'],
        food_consumed=results_dict['pellets_consumed'],
        successful_reaches=results_dict['successful_reaches'],
        pellets_presented=results_dict['pellets_presented'],
    )
