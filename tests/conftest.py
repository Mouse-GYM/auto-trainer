from pathlib import Path

import pytest

from autotrainer.behavior import DiamondTriangleOffsetConfig, BehaviorAlgorithm
from autotrainer.core import SystemConfiguration, CameraConfiguration, CameraId
from autotrainer.device import MotorConfigurationFile, CompoundMovements

from tools.acquisition.model.app_model import AppModel
from tools.acquisition.model.user_preferences import UserPreferences


this_dir = Path(__file__).parent
top_dir = this_dir.parent  # supposed be the repo top/root dir


@pytest.fixture
def trainer_config_dir(tmp_path):
    cfg_dir = tmp_path.joinpath("Autotrainer")
    cfg_dir.mkdir()
    return cfg_dir


@pytest.fixture
def system_config(trainer_config_dir, tmp_path):
    config = SystemConfiguration()
    for cam_member in (CameraId.Left, CameraId.Right, CameraId.Web):
        params = dict(width=300, height=200)
        cam = CameraConfiguration(name=cam_member.name, params=params)
        cam.scheme = "random"
        cam.id = cam_member
        config.cameras.append(cam)
    config.persistence.output_location = tmp_path.joinpath("Data").as_posix()
    config.save_default(trainer_config_dir)
    return config


@pytest.fixture
def config_file_path(trainer_config_dir):
    return trainer_config_dir.joinpath(SystemConfiguration.make_default_yaml_config_path(trainer_config_dir))


@pytest.fixture
def animals_dir(tmp_path):
    path = tmp_path.joinpath("animals")
    path.mkdir()
    return path


@pytest.fixture
def settings_ini_path(tmp_path):
    return tmp_path.joinpath("settings.ini")


@pytest.fixture
def user_pref(tmp_path, trainer_config_dir, animals_dir, settings_ini_path):
    pref = UserPreferences(settings_file_path=settings_ini_path)
    pref.configuration_location = trainer_config_dir
    pref.animal_location = animals_dir
    p = tmp_path.joinpath("logs")
    p.mkdir()
    pref.log_location = p
    return pref


@pytest.fixture
def calib_dir():
    # could be todo: copy it top-level, or generate new temporary one as above for system config.
    return top_dir.joinpath("auto-trainer-inference/tests/4mm_6r_8c_4x")


@pytest.fixture(autouse=True)
def diamond_config_path(monkeypatch):
    path = this_dir.joinpath("diamond_triangle_offset.yaml")
    monkeypatch.setattr(DiamondTriangleOffsetConfig, 'DEFAULT_CONFIG_PATH', path)
    # prev_default = DiamondTriangleOffsetConfig.DEFAULT_CONFIG_PATH
    # DiamondTriangleOffsetConfig.DEFAULT_CONFIG_PATH = path
    yield path
    # DiamondTriangleOffsetConfig.DEFAULT_CONFIG_PATH = prev_default


@pytest.fixture
def app_model(user_pref, calib_dir, diamond_config_path, system_config, monkeypatch):
    # for now:
    monkeypatch.setattr(BehaviorAlgorithm, "_no_handler_thread", True)
    assert BehaviorAlgorithm._no_handler_thread is True  # to be safe to start with
    #
    app = AppModel(user_pref, calib_dir=calib_dir)
    return app
