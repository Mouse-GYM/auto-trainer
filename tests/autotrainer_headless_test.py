import os
import re
import signal
import subprocess
import sys
import threading
import time

import pytest

from pathlib import Path

import verboselogs

from autotrainer.behavior import DiamondTriangleOffsetConfig, BehaviorAlgorithm
from autotrainer.core import SystemConfiguration, CameraConfiguration, CameraId
from tools.acquisition.model.app_model import AppModel
from tools.acquisition.model.user_preferences import UserPreferences


import top_fixtures

headless_path = top_fixtures.repo_root_dir.joinpath("auto-trainer-headless.py")


def remove_ansi_escape_sequences(s):
    # Regex for common ANSI escape codes
    ansi_escape = re.compile(r'(\x9B|\x1B\[)[0-?]*[ -/]*[@-~]')
    return ansi_escape.sub('', s)


@pytest.fixture
def system_config(trainer_config_dir, tmp_path):
    config = SystemConfiguration()
    for cam_member in (CameraId.Left, CameraId.Right, CameraId.Web):
        params = dict(width=300, height=200, primary="yes" if cam_member is CameraId.Left else "no")
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
    pref.log_level = int(verboselogs.VERBOSE)
    return pref


@pytest.fixture
def calib_dir():
    # could be todo: copy it top-level, or generate new temporary one as above for system config.
    return top_fixtures.repo_root_dir.joinpath("auto-trainer-inference/tests/4mm_6r_8c_4x")


@pytest.fixture
def diamond_config_path(monkeypatch):
    path = top_fixtures.repo_root_tests_subdir.joinpath("diamond_triangle_offset.yaml")
    # prev_default = DiamondTriangleOffsetConfig.DEFAULT_CONFIG_PATH
    monkeypatch.setattr(DiamondTriangleOffsetConfig, "DEFAULT_CONFIG_PATH", path)
    yield path


@pytest.fixture
def app_model(user_pref, calib_dir, diamond_config_path, system_config, monkeypatch):
    # for now:
    monkeypatch.setattr(BehaviorAlgorithm, "_no_handler_thread", True)
    assert BehaviorAlgorithm._no_handler_thread is True  # to be safe to start with
    #
    app = AppModel(user_pref, calib_dir=calib_dir)
    return app


def test_user_preferences(settings_ini_path, user_pref, trainer_config_dir):
    assert Path(user_pref._settings.fileName()) == settings_ini_path
    assert not settings_ini_path.exists()
    user_pref.selected_animal = "foobar"
    user_pref.save()
    assert settings_ini_path.exists()
    user_pref = UserPreferences(settings_file_path=settings_ini_path)
    assert Path(user_pref.configuration_location) == trainer_config_dir
    assert user_pref.selected_animal == "foobar"


def test_load_config(app_model, trainer_config_dir, animals_dir, calib_dir, system_config):
    res = app_model.load_configuration()
    assert res is True
    assert app_model.left_camera.name == "left"
    assert app_model.right_camera.name == "right"
    assert app_model.top_camera.name == "web"
    assert app_model.output_location == system_config.persistence.output_location
    pref = app_model.preferences
    assert Path(pref.animal_location) == animals_dir
    assert Path(pref.configuration_location) == trainer_config_dir

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


@pytest.mark.skipif(sys.platform.startswith("win"), reason="hang atm. mostlikely signal related, different on windows")
def test_launch_cli(system_config, user_pref, calib_dir, diamond_config_path, config_file_path, settings_ini_path):
    user_pref.save()  # do not forget ! otherwise default home config dirs/files are used
    env = os.environ.copy()
    env['AUTOTRAINER_DIAMOND_TRIANGLE_CONFIG'] = diamond_config_path.as_posix()  # same for this !
    env['AUTOTRAINER_FORCE_CAN_EMULATION_IFACE'] = "1"
    proc = subprocess.Popen([
        sys.executable, headless_path,
        "-c", config_file_path.as_posix(),
        "--preferences-file", settings_ini_path.as_posix(),
    ], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=-1)
    #
    out = []
    err = []
    # NB: for now we wait a fixed amount of time and then interrupt the app:
    def interrupt_proc():
        t_end = time.perf_counter() + 25
        while time.perf_counter() < t_end:
            if any("App is now running" in line for line in out):
                break
            time.sleep(0.05)
        proc.send_signal(signal.SIGINT)
    t = threading.Thread(target=interrupt_proc, daemon=True)
    t.start()
    def communicate(dest, src_fh, dest_fh):
        while proc.poll() is None:
            line = src_fh.readline()  # .decode()
            line = line.strip(b'\n').decode()
            print(line, file=dest_fh)
            dest.append(remove_ansi_escape_sequences(line))
        tail = src_fh.read().decode()
        print(tail, file=dest_fh)
        dest.extend(tail.split("\n"))
        # out, err = proc.communicate()
    communicate_out_thread = threading.Thread(target=communicate, daemon=True, args=(out, proc.stdout, sys.stdout))
    communicate_out_thread.start()  # use a communicate thread, given otherwise it might stay blocked ignoring the SIGINT
    communicate_err_thread = threading.Thread(target=communicate, daemon=True, args=(err, proc.stderr, sys.stderr))
    communicate_err_thread.start()  # use a communicate thread, given otherwise it might stay blocked ignoring the SIGINT
    t.join()

    communicate_out_thread.join(3)

    proc.terminate()  # in case of
    proc.wait(3)  # in case of
    proc.kill()  # in case of
    communicate_out_thread.join()
    communicate_err_thread.join()
    assert proc.returncode == 0
    output = "\n".join(out)
    # print(output)
    assert f"Loading diamond-triangle file {diamond_config_path.as_posix()!r}" in output
    assert f"Using setting ini file: {settings_ini_path.as_posix()!r}" in output
    assert "Alogus hardware or hardware support not found. Using emulation interface." in output
    assert f"Writing to {config_file_path.as_posix()!r}" in output
    # etc...
