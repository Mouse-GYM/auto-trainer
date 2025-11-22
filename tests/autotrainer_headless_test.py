import os
import signal
import subprocess
import sys
import threading
import time

import pytest

from pathlib import Path

from autotrainer.behavior import DiamondTriangleOffsetConfig, BehaviorAlgorithm
from autotrainer.core import SystemConfiguration, CameraConfiguration, CameraId
from tools.acquisition.model.app_model import AppModel
from tools.acquisition.model.user_preferences import UserPreferences


top_dir = Path(__file__).parent.parent  # supposed be the repo top/root dir
headless_path = top_dir.joinpath("auto-trainer-headless.py")


@pytest.fixture
def config_dir(tmp_path):
    cfg_dir = tmp_path.joinpath("Autotrainer")
    cfg_dir.mkdir()
    config = SystemConfiguration()
    for cam_member in (CameraId.Left, CameraId.Right, CameraId.Web):
        params = dict(width=300, height=200)
        cam = CameraConfiguration(name=cam_member.name, params=params)
        cam.scheme = "random"
        cam.id = cam_member
        config.cameras.append(cam)
    config.save_default(cfg_dir)
    return cfg_dir


@pytest.fixture
def config_file_path(config_dir):
    return config_dir.joinpath(SystemConfiguration.make_default_yaml_config_path(config_dir))


@pytest.fixture
def animals_dir(tmp_path):
    path = tmp_path.joinpath("animals")
    path.mkdir()
    return path


@pytest.fixture
def settings_ini_path(tmp_path):
    return tmp_path.joinpath("settings.ini")


@pytest.fixture
def user_pref(tmp_path, config_dir, animals_dir, settings_ini_path):
    pref = UserPreferences(settings_file_path=settings_ini_path)
    pref.configuration_location = config_dir
    pref.animal_location = animals_dir
    p = tmp_path.joinpath("logs")
    p.mkdir()
    pref.log_location = p
    return pref


@pytest.fixture
def calib_dir(config_dir):
    # could be todo: copy it top-level, or generate new temporary one as above for system config.
    return top_dir.joinpath("auto-trainer-inference/tests/4mm_6r_8c_4x")


@pytest.fixture
def diamond_config_path(config_dir):
    path = config_dir.joinpath("diamond_triangle.yaml")
    prev_default = DiamondTriangleOffsetConfig.DEFAULT_CONFIG_PATH
    DiamondTriangleOffsetConfig.DEFAULT_CONFIG_PATH = path
    yield path
    DiamondTriangleOffsetConfig.DEFAULT_CONFIG_PATH = prev_default


@pytest.fixture
def app_model(user_pref, calib_dir, diamond_config_path):
    # for now:
    BehaviorAlgorithm._no_handler_thread = True  # to be safe to start with
    #
    app = AppModel(user_pref, calib_dir=calib_dir)
    return app


def test_user_preferences(settings_ini_path, user_pref, config_dir):
    assert Path(user_pref._settings.fileName()) == settings_ini_path
    assert not settings_ini_path.exists()
    user_pref.selected_animal = "foobar"
    user_pref.save()
    assert settings_ini_path.exists()
    user_pref = UserPreferences(settings_file_path=settings_ini_path)
    assert Path(user_pref.configuration_location) == config_dir
    assert user_pref.selected_animal == "foobar"


def test_load_config(app_model, config_dir, animals_dir, calib_dir, settings_ini_path):
    res = app_model.load_configuration()
    assert res is True
    assert app_model.left_camera.name == "left"
    assert app_model.right_camera.name == "right"
    assert app_model.top_camera.name == "web"
    assert app_model.output_location == ""
    pref = app_model.preferences
    assert Path(pref.animal_location) == animals_dir
    assert Path(pref.configuration_location) == config_dir

    # ...


def test_start_stop(app_model, settings_ini_path):
    assert not settings_ini_path.exists()
    assert app_model.load_configuration() is True
    assert app_model.on_capture_start() is True
    app_model.on_capture_stop()
    assert not settings_ini_path.exists()  # still
    app_model.on_close()
    assert settings_ini_path.exists()  # but saved on close
    # ...


def test_cli_help():
    output = subprocess.check_output([sys.executable, headless_path, "-h"]).decode()
    assert "usage: auto-trainer-headless.py" in output


# @pytest.mark.functional
def test_launch_cli(config_dir, user_pref, calib_dir, diamond_config_path, config_file_path, settings_ini_path):
    user_pref.save()  # do not forget ! otherwise default home config dirs/files are used
    env = os.environ.copy()
    env['AUTOTRAINER_DIAMOND_TRIANGLE_CONFIG'] = diamond_config_path.as_posix()  # same for this !
    proc = subprocess.Popen([
        sys.executable, headless_path,
        "-c", config_file_path.as_posix(),
        "--preferences-file", settings_ini_path.as_posix(),
    ], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=-1)
    def interrupt_proc():
        time.sleep(15)  # with 5s or event 10s sometimes it's too slow to output what we expect/assert below..
        proc.send_signal(signal.SIGINT)
    t = threading.Thread(target=interrupt_proc, daemon=True)
    t.start()
    out = err = None
    def communicate():
        nonlocal out, err
        out, err = proc.communicate()
    communicate_thread = threading.Thread(target=communicate, daemon=True)
    communicate_thread.start()  # use a communicate thread, given otherwise it might stay blocked ignoring the SIGINT
    t.join()
    communicate_thread.join(20)
    proc.terminate()  # in case of
    proc.wait(3)  # in case of
    proc.kill()  # in case of
    assert proc.returncode == 0
    assert isinstance(out, bytes)
    output = out.decode()
    print(output)
    assert f"Diamond triangle config {diamond_config_path.as_posix()!r} not a file" in output
    assert f"Using setting ini file: {settings_ini_path.as_posix()!r}" in output
    #
    assert "Alogus hardware or hardware support not found. Using emulation interface." in output
    # etc...
