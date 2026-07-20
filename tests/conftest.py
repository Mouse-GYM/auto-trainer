from pathlib import Path

import pytest

from autotrainer.behavior import BehaviorAlgorithm
from autotrainer.core.configuration import DEFAULT_3D_CALIB_DIR_NAME
from autotrainer.core.diamond_triangle_config import DiamondTriangleOffsetConfig
from autotrainer.core import SystemConfiguration, CameraConfiguration, CameraId
from autotrainer.device import MotorConfigurationFile, CompoundMovements

from tools.acquisition.model.app_model import AppModel
from tools.acquisition.model.user_preferences import UserPreferences


import top_fixtures


@pytest.fixture
def system_config(trainer_config_dir, tmp_path):
    config = SystemConfiguration()
    # mostly ~all default params are good, but we need:
    config.behavior.pellet_delivery.is_enabled = True
    config.behavior.pellet_delivery.is_intertrial_analysis_enabled = True
    for cam_member in (CameraId.Left, CameraId.Right, CameraId.Web):
        params = dict(width=300, height=200)
        cam = CameraConfiguration(name=cam_member.name, params=params)
        cam.record_prebuffer_duration = 0
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
def calib_dir():
    # could be todo: copy it top-level, or generate new temporary one as above for system config.
    return top_fixtures.repo_root_dir.joinpath(f"auto-trainer-inference/tests/{DEFAULT_3D_CALIB_DIR_NAME}")


@pytest.fixture
def app_model(mock_system, user_pref, calib_dir, diamond_config_path, system_config, monkeypatch, fake_system_msg_handler):
    # for now:
    monkeypatch.setattr(BehaviorAlgorithm, "_no_handler_thread", True)
    assert BehaviorAlgorithm._no_handler_thread is True  # to be safe to start with
    #
    app = AppModel(
        user_pref,
        system_machine=mock_system.system_machine,
        sensor_analysis=mock_system.sensor_analysis,
        inference_model=mock_system.inference,
        system_message_handler=fake_system_msg_handler,
        calib_dir=calib_dir,
    )
    # ensure all of that is not async:
    analysis = app.analysis
    analysis.emergency_alarm_monitor.default_timer_delay = None
    analysis.emergency_alarm_monitor.use_daemon = False
    for alarm_det in analysis.alarms:
        alarm_det.use_daemon = False
        alarm_det.default_timer_delay = None
        alarm_det.restart()
    for det in analysis.detectors:
        det.use_daemon = False
        det.default_timer_delay = None
        det.restart()
    # also ensure watchdogs is/are disabled:
    analysis.watchdog_monitor.config.use = False
    for watch_det in analysis.watchdog_monitor.watchdog_items:
        watch_det.config.use = False
    try:
        yield app
    finally:
        app.on_close()
