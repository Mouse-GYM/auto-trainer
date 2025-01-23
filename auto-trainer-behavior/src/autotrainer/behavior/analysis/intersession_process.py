import logging
from dataclasses import dataclass

import numpy

from autotrainer.core import ProjectInfo, video_write_ext

from .prepare_jetson_data import process_raw_data
from .parse_pellet_presentations_jetson import segment_reaches

logger = logging.getLogger(__name__)

available_XYZ = numpy.array([[-5, 5], [-5, 5], [-5, 5]])


@dataclass
class IntersessionResponse:
    pellet_x: int = 0
    pellet_y: int = 0
    pellet_z: int = 0
    food_consumed: int = 0
    baseline_intensity_adjust: int = 0


def intersession_process(project: ProjectInfo) -> IntersessionResponse:
    """
    Called after pose processing for intersession analysis.

    :param project: current project info for finding/defining file names
    :return: information required to update behavior for future sessions
    """
    # left_input = project.get_intersession_pose_path(name=project.camera_1, allow_overwrite=True)
    # right_input = project.get_intersession_pose_path(name=project.camera_2, allow_overwrite=True)
    location, _, _ = project.get_session_path()

    logger.info(f"process intersession pose data using {location}")

    calib_src_dir = "/home/agx001/3d-calibration/4mm_6r_8c_4x"
    vid_tag = "." + video_write_ext
    dlc_seg = "_raw2D"
    center_method = (1, "Pellet")
    process_raw_data(location, vid_tag, dlc_seg, calib_src_dir, center_method)
    results_dict = segment_reaches(location, center_method, available_XYZ)

    logger.info(f"process intersession pose data complete {results_dict}")

    return IntersessionResponse()
