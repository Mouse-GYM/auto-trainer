from pathlib import Path

import yaml

import pytest

from autotrainer.core.analysis import calibration_FLIR
from autotrainer.core.analysis.config import load_calib_stereo_params
from autotrainer.core.configuration import DEFAULT_3D_CALIB_DIR_NAME
from autotrainer.inference.pose_algorithm import PoseAlgorithm


this_dir = Path(__file__).parent


@pytest.fixture
def calib_dir_path():
    return this_dir.joinpath(DEFAULT_3D_CALIB_DIR_NAME)


@pytest.fixture
def stereo_params(calib_dir_path):
    params = load_calib_stereo_params(calib_dir_path.joinpath("camera_matrix/stereo_params.pickle"))
    return params


@pytest.fixture
def calib_metadata(calib_dir_path):
    metadata_path = calib_dir_path.joinpath('calibration_userset.yaml')
    with metadata_path.open() as fh:
        return yaml.safe_load(fh)


@pytest.fixture
def pose_algo(calib_dir_path, stereo_params, calib_metadata):
    calib_info = calibration_FLIR.get_calibration_info(calib_dir_path.as_posix())
    square_size = calib_info[0]
    return PoseAlgorithm(
        cam_names=["20241029_agx001_session002_left", "20241029_agx001_session002_right"],
        stereo_params=stereo_params,
        calib_metadata=calib_metadata,
        square_size=square_size,
    )
