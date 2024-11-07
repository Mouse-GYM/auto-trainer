import logging
from dataclasses import dataclass

from autotrainer.core import ProjectInfo

logger = logging.getLogger(__name__)


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
    left_input = project.get_intersession_pose_path(name=project.camera_1, allow_overwrite=True)
    right_input = project.get_intersession_pose_path(name=project.camera_2, allow_overwrite=True)

    logger.info(f"process intersession pose data using {left_input}, {right_input}")

    return IntersessionResponse()
