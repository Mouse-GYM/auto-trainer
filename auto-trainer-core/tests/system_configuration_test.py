import copy
import dataclasses
import datetime
import io
import shutil
from pathlib import Path

import humps
import pytest
import yaml

from autotrainer.core import (
    SystemConfiguration,
    CameraId,
    CameraConfiguration,
    Offset3DTuple
)
from autotrainer.core.configuration.device_comm_alarm_config import DeviceCommAlarmConfig
from autotrainer.core.configuration.load_cell_config import LoadCellConfiguration
from autotrainer.core.configuration.audio_thrash_config import AudioSpectrumThrashMonitorConfig
from autotrainer.core.configuration import (
    SystemConfigurationDumper,
    SystemConfigurationLoader,
)
from autotrainer.core.configuration.alarm_configuration import EmergencyAlarmConfiguration
from autotrainer.core.configuration.behavior_configuration import PelletDeliveryConfiguration, HeadClampConfiguration, \
    AutoEndTrialConfiguration, BatchTrialRecordingConfiguration, AutoCloseGateOnIntertrialConfiguration, \
    AnimalSleepWindow, TimePeriod
from autotrainer.core.configuration.hardware_configuration import HardwareConfiguration


fixtures_path = Path(__file__).parent.joinpath("fixtures")

v0_config_path = fixtures_path.joinpath("v0_config.yaml")
v1_config_path = fixtures_path.joinpath("v1_config.yaml")
v51_config_path = fixtures_path.joinpath("v51_config.yaml")

#

audio_cfg = AudioSpectrumThrashMonitorConfig()
emergency_alarm_cfg = EmergencyAlarmConfiguration()

current_default_config_dict = dataclasses.asdict(SystemConfiguration())

behavior_default_config_dict = current_default_config_dict['behavior']


v0_expected_result_config = {
    "version": SystemConfiguration.version,
    "cameras": [
        {
            "id": CameraId.Left,
            "name": "left",
            "is_enabled": True,
            "is_record_enabled": True,
            "record_mode": 1,
            "record_prebuffer_duration": CameraConfiguration.record_prebuffer_duration,
            "is_still_image_capture_enabled": True,
            "still_image_capture_interval": 10.5,
            "scheme": "random",
            "host": "0",
            "port": 0,
            "path": "",
            "params": {"width": 300, "height": 200},
        },
        {
            "id": CameraId.Right,
            "name": "right",
            "is_enabled": True,
            "is_record_enabled": True,
            "record_mode": 1,
            "record_prebuffer_duration": CameraConfiguration.record_prebuffer_duration,
            "is_still_image_capture_enabled": False,
            "still_image_capture_interval": 0.0,
            "scheme": "random",
            "host": "0",
            "port": 0,
            "path": "",
            "params": {"width": 300, "height": 200},
        },
        {
            "id": CameraId.Web,
            "name": "Random Image",
            "is_enabled": True,
            "is_record_enabled": False,
            "record_mode": 0,
            "record_prebuffer_duration": CameraConfiguration.record_prebuffer_duration,
            "is_still_image_capture_enabled": False,
            "still_image_capture_interval": 0.0,
            "scheme": "random",
            "host": "0",
            "port": 0,
            "path": "",
            "params": {"width": 300, "height": 200},
        },
    ],
    "hardware": {
        "tunnel_identifier": "COM24",
        "pellet_identifier": "COM28",
        "min_ack_timeout": None,
        "board_status_timeout": None,
        "camera_start_timeout": HardwareConfiguration.camera_start_timeout,
    },
    "inference": {
        "pose_model_location": "/home/autotrainer/models/current-model-2000-01-02",
        "is_enabled": True,
    },
    "behavior": {
        "pellet_delivery": {
            "is_enabled": True,
            "retract_enabled": True,
            "is_pellet_cover_enabled": True,
            "is_intertrial_analysis_enabled": True,
            "is_intertrial_pellet_shift_enabled": True,
            "pellet_send_wait_delay": 1.0,
            "max_pellets_per_trial": 20,
            "max_pellets_per_day": 25,
            "max_pellet_missing_seconds": 10,
            "auto_correct_motors_drift": False,
            "triangle_pellet_expected_distance": PelletDeliveryConfiguration.triangle_pellet_expected_distance,
            "triangle_pellet_diff_too_far_threshold": PelletDeliveryConfiguration.triangle_pellet_diff_too_far_threshold,
            "use_triangle_pellet_distance_too_far": PelletDeliveryConfiguration.use_triangle_pellet_distance_too_far,
        },
        "head_clamp": {
            "baseline_intensity": 0.0,
            "auto_clamp_intensity": 80,
            "auto_clamp_release_tone_freq": 6000,
            "auto_clamp_release_tone_delay": 0.2,
            "auto_clamp_no_activity_release_delay": HeadClampConfiguration.auto_clamp_no_activity_release_delay,
            "auto_clamp_release_load_count": HeadClampConfiguration.auto_clamp_release_load_count,
            "before_reengage_delay": HeadClampConfiguration.before_reengage_delay,
        },
        "load_cell": {
            "weight_active_threshold": 10,
            "weight_inactive_threshold": 2,
            "threshold_duration": 0.2,
            "min_event_duration": 4.0,
            "min_post_event_hold_duration": 3.0,
            "thrashing_var_weight_threshold_min": 20,
            "thrashing_var_weight_threshold_max": 30,
            "thrashing_var_min_delay": 0.05,
            "thrashing_var_max_delay": 0.2,
            "thrashing_min_ptp_change_count": 3,
            "weight_min_filter": LoadCellConfiguration.weight_min_filter,
            "weight_max_filter": LoadCellConfiguration.weight_max_filter,
        },
        "headbar_pressure": {"threshold": 10, "duration": 1.5},
        "auto_tare": {
            "threshold": 1.1,
            "range_threshold": 1.75,
            "duration": 1.0,
            "sample_rate": 100,
        },
    },
    "persistence": {"output_location": "/home/autotrainer/output"},
}


def _fill_v0():
    v0_behavior = v0_expected_result_config['behavior']
    for k, v in behavior_default_config_dict.items():
        if k not in v0_behavior:
            v0_behavior[k] = copy.deepcopy(v)
    v0_headclamp = v0_behavior['head_clamp']
    for k, v in behavior_default_config_dict['head_clamp'].items():
        if k not in v0_headclamp:
            v0_headclamp[k] = copy.deepcopy(v)
    v0_expected_result_config["watchdog"] = current_default_config_dict["watchdog"]

_fill_v0()


def test_load_version_zero():
    # All the values in this file are different from the defaults, when originally written.
    configuration = SystemConfiguration.load_yaml_file(v0_config_path, save_backup=False)
    assert dataclasses.asdict(configuration) == v0_expected_result_config


def test_round_trip():
    # Load from a version 0 file and assert that is not a SystemConfiguration dump w/YAML tags.
    # Dump from SystemConfiguration and assert that it is a SystemConfiguration dump w/YAML tags and subsequent load
    #     will go through the SystemConfiguration custom loader.
    # Load that output and verify values

    assert "!SystemConfiguration" not in v0_config_path.read_text()
    configuration = SystemConfiguration.load_yaml_file(v0_config_path, save_backup=False)

    saved = configuration.dump_yaml()
    assert "!SystemConfiguration" in saved

    reloaded = SystemConfiguration.load_yaml(io.StringIO(saved))
    assert dataclasses.asdict(reloaded) == v0_expected_result_config


def test_load_version_1():
    # All the values in this file are different from the defaults, when originally written.
    path = fixtures_path.joinpath("v1_config.yaml")
    with path.open() as fh:
        config = SystemConfiguration.load_yaml(fh)
    exp_load_cell = copy.deepcopy(v0_expected_result_config['behavior']['load_cell'])
    exp_load_cell.update({
        'min_event_duration': 3.0,
            'min_post_event_hold_duration': 6.0,
            'thrashing_min_ptp_change_count': 3,
            'thrashing_var_max_delay': 0.2,
            'thrashing_var_min_delay': 0.05,
            'thrashing_var_weight_threshold_max': 30,
            'thrashing_var_weight_threshold_min': 20,
            'threshold_duration': 0.25,
            'weight_active_threshold': 15.0,
            'weight_inactive_threshold': 2,
    })
    expected_behavior = copy.deepcopy(behavior_default_config_dict)
    expected_behavior["load_cell"] = exp_load_cell
    expected_behavior["pellet_delivery"].update({
                'is_enabled': False,
                'is_intertrial_analysis_enabled': True,
                'is_intertrial_pellet_shift_enabled': True,
                'is_pellet_cover_enabled': True,
                'max_pellet_missing_seconds': 15,
                'max_pellets_per_day': 75,
                'max_pellets_per_trial': 10,
                'auto_correct_motors_drift': False,
                'triangle_pellet_expected_distance': PelletDeliveryConfiguration.triangle_pellet_expected_distance,
                'triangle_pellet_diff_too_far_threshold': PelletDeliveryConfiguration.triangle_pellet_diff_too_far_threshold,
                'use_triangle_pellet_distance_too_far': PelletDeliveryConfiguration.use_triangle_pellet_distance_too_far,
            }
    )
    # for k, v in behavior_default_config_dict.items():
    #     if k not in expected_behavior:
    #         expected_behavior[k] = v
    assert dataclasses.asdict(config) == {
        'behavior': expected_behavior,
        'cameras': [{'host': None,
                     'id': CameraId.Left,
                     'is_enabled': True,
                     'is_record_enabled': True,
                     'is_still_image_capture_enabled': False,
                     'name': 'left',
                     'params': {'fps': 150, 'height': 256, 'width': 256},
                     'path': '/path_cam_left',
                     'port': 0,
                     'record_mode': 1,
                     'record_prebuffer_duration': CameraConfiguration.record_prebuffer_duration,
                     'scheme': 'playback',
                     'still_image_capture_interval': 0.0},
                    {'host': 'cam1_host',
                     'id': CameraId.Right,
                     'is_enabled': True,
                     'is_record_enabled': True,
                     'is_still_image_capture_enabled': False,
                     'name': 'right',
                     'params': {'fps': 150, 'height': 256, 'width': 256},
                     'path': '/path_cam_right',
                     'port': 0,
                     'record_mode': 1,
                     'record_prebuffer_duration': CameraConfiguration.record_prebuffer_duration,
                     'scheme': 'playback',
                     'still_image_capture_interval': 0.0},
                    {'host': 'cam2_host',
                     'id': CameraId.Web,
                     'is_enabled': True,
                     'is_record_enabled': False,
                     'is_still_image_capture_enabled': False,
                     'name': 'web',
                     'params': {'fps': 30, 'height': 1080, 'width': 1920},
                     'path': '/path_cam_web',
                     'port': 0,
                     'record_mode': 0,
                     'record_prebuffer_duration': CameraConfiguration.record_prebuffer_duration,
                     'scheme': 'playback',
                     'still_image_capture_interval': 0.0}],
        'hardware': {'pellet_identifier': '/dev/ttyS31',
                     'tunnel_identifier': '/dev/ttyS30',
                     'min_ack_timeout': None, 'board_status_timeout': None,
                     "camera_start_timeout": HardwareConfiguration.camera_start_timeout,
                     },
        'inference': {'is_enabled': True,
                      'pose_model_location': '/pose_model_path'},
        'persistence': {'output_location': '/output_location_path'},
        'watchdog': current_default_config_dict["watchdog"],
        'version': SystemConfiguration.version}


def test_same_version_unknown_attribute_raise():
    config_text = f"""
!SystemConfiguration
version: {SystemConfiguration.version}
unknown_attribute: 42
"""
    with pytest.raises(TypeError, match="unknown_attribute"):
        SystemConfiguration.load_yaml(io.StringIO(config_text))


def test_higher_version_drop_unknown_config_items():
    config_text = f"""
!SystemConfiguration
version: {SystemConfiguration.version + 1}
unknown_attribute: 42
persistence: !PersistenceConfiguration
  outputLocation: /output_location_path
  another_unknown_attribute: foobar
"""
    cfg = SystemConfiguration.load_yaml(io.StringIO(config_text))
    assert isinstance(cfg, SystemConfiguration)
    expected_result = copy.deepcopy(current_default_config_dict)
    # apart the version and persistence.output_location, these are all the defaults values
    expected_result["version"] = SystemConfiguration.version + 1
    expected_result["persistence"]["output_location"] = "/output_location_path"
    assert dataclasses.asdict(cfg) == expected_result


def test_safe_loader_ignore_unknown_tags():
    config_text = f"""
    !SystemConfiguration
    version: {SystemConfiguration.version + 1}
    unknown_attribute: 42
    bar: !unknown_tag
    baz:
    - !second_unknown_tag
      param1: anything
    """
    cfg = SystemConfiguration.load_yaml(io.StringIO(config_text))
    assert isinstance(cfg, SystemConfiguration)
    expected_result = copy.deepcopy(current_default_config_dict)
    # apart the version, these are all the defaults values
    expected_result["version"] = SystemConfiguration.version + 1
    assert dataclasses.asdict(cfg) == expected_result


def test_save_file_without_specify_save_type_fails():
    cfg = SystemConfiguration()
    with pytest.raises(ValueError, match="Missing one of as_json or as_yaml"):
        cfg.save_file("foobar.baz")


def test_offset3d_yaml():
    o = Offset3DTuple(1, 2, 3.5)
    data = yaml.dump(o, Dumper=SystemConfigurationDumper)
    o2 = yaml.load(data, Loader=SystemConfigurationLoader)
    assert isinstance(o2, Offset3DTuple)
    assert o2 == o


def test_device_comm_default():
    cfg = DeviceCommAlarmConfig()
    assert cfg.is_emergency_condition is True


@pytest.mark.parametrize("analysis_enabled", (False, True))
@pytest.mark.parametrize("max_pellets", (0, 15))
@pytest.mark.parametrize("shift_enabled", (False, True))
@pytest.mark.parametrize("auto_end_session", (
    AutoEndTrialConfiguration(no_activity_delay_minutes=12),
    AutoEndTrialConfiguration(no_activity_delay_minutes=15),
))
def test_renames_on_v52_are_respected(
    analysis_enabled,
    max_pellets,
    shift_enabled,
    auto_end_session,
):
    config_text = f"""
    !SystemConfiguration
    version: 51
    behavior: !BehaviorConfiguration
        pelletDelivery: !PelletDeliveryConfiguration
            isIntersessionAnalysisEnabled: {"true" if analysis_enabled else "false"}
            isIntersessionPelletShiftEnabled: {"true" if shift_enabled else "false"}
            maxPelletsPerSession: {max_pellets}
        autoEndSession: !AutoEndSessionConfiguration
            noActivityDelayMinutes: {auto_end_session.no_activity_delay_minutes}
            animalTunnelNoActivityDelay: {auto_end_session.animal_tunnel_no_activity_delay}
    """
    cfg = SystemConfiguration.load_yaml(io.StringIO(config_text))
    assert isinstance(cfg, SystemConfiguration)
    assert cfg.behavior.pellet_delivery.is_intertrial_analysis_enabled is analysis_enabled
    assert cfg.behavior.pellet_delivery.is_intertrial_pellet_shift_enabled is shift_enabled
    assert cfg.behavior.pellet_delivery.max_pellets_per_trial == max_pellets
    assert cfg.behavior.auto_end_trial == auto_end_session


def test_renamed_batch_and_close_gate_on_v52_are_respected():
    config_text = """
    !SystemConfiguration
    version: 51
    behavior: !BehaviorConfiguration
        batchSessionRecording: !BatchSessionRecordingConfiguration
            enabled: true
            maximumBatchSize: 5
        autoCloseGateOnIntersession: !AutoCloseGateOnIntersessionConfiguration
            enabled: true
            sessionMinDuration: 42
    """
    cfg = SystemConfiguration.load_yaml(io.StringIO(config_text))
    assert isinstance(cfg, SystemConfiguration)
    assert cfg.behavior.batch_trial_recording == BatchTrialRecordingConfiguration(
        enabled=True, maximum_batch_size=5)
    assert cfg.behavior.auto_close_gate_on_intertrial == AutoCloseGateOnIntertrialConfiguration(
        enabled=True, trial_min_duration=42)


def test_load_older_version_camera_id_is_camera_id_enum():
    config_text = """
    !SystemConfiguration
    version: 51
    cameras:
    - !CameraConfiguration
      id: 0
      name: left
    - !CameraConfiguration
      id: 2
      name: web
    """
    cfg = SystemConfiguration.load_yaml(io.StringIO(config_text))
    # equality alone would hold for a plain int, CameraId being an IntEnum:
    assert [type(cam.id) for cam in cfg.cameras] == [CameraId, CameraId]
    assert [cam.id for cam in cfg.cameras] == [CameraId.Left, CameraId.Web]


def test_load_version_51_file(tmp_path):
    # loading with save_backup rewrites the file in place on a version change, so work on a copy:
    path = tmp_path.joinpath("system_configuration.yaml")
    shutil.copy2(v51_config_path, path)

    config = SystemConfiguration.load_yaml_file(path, save_backup=True)

    assert config.version == SystemConfiguration.version

    assert [type(cam.id) for cam in config.cameras] == [CameraId] * 3
    assert [cam.id for cam in config.cameras] == [CameraId.Left, CameraId.Right, CameraId.Web]
    assert [cam.name for cam in config.cameras] == ["left", "right", "web"]
    left, _right, web = config.cameras
    assert left.scheme == "spinnaker"
    assert left.host == "23199919"
    assert left.record_mode == 1
    assert left.params == dict(exposure=250, fps=150, hbin=4, vbin=4, width=256, height=256,
                               offsetx=52, offsety=6, gain=1, gamma=0.7, primary=True)
    assert web.is_still_image_capture_enabled is True
    assert web.still_image_capture_interval == 1.0

    # the yaml tags are dropped when re-reading an older config, so these carry the types they used to:
    shift_xyz = config.behavior.shift_xyz_handler
    assert shift_xyz.tongue_eaten_shift == Offset3DTuple(0, 0.5, 0)
    assert isinstance(shift_xyz.tongue_eaten_shift, Offset3DTuple)
    assert shift_xyz.buffer.target == Offset3DTuple(1.5, -3, 1)
    assert isinstance(shift_xyz.buffer.target, Offset3DTuple)

    ign_window = config.behavior.animal_sleep_window
    assert ign_window.start == datetime.time(10, 0)
    assert isinstance(ign_window.start, datetime.time)
    assert ign_window.stop == datetime.time(20, 0)

    # the v52 renames, as they appear in a real v51 file:
    pellet_delivery = config.behavior.pellet_delivery
    assert pellet_delivery.max_pellets_per_trial == 10
    assert pellet_delivery.is_intertrial_analysis_enabled is True
    assert pellet_delivery.is_intertrial_pellet_shift_enabled is False
    assert config.behavior.auto_end_trial.no_activity_delay_minutes == 1
    assert config.behavior.batch_trial_recording.maximum_batch_size == 0
    assert config.behavior.auto_close_gate_on_intertrial.trial_min_duration == 5

    assert config.persistence.output_location == "/home/autotrainer/auto-trainer-output"
    assert config.behavior.head_clamp.release_mode == "Activity"
    assert config.watchdog.timeout_trigger_delay == 5


def test_load_version_51_file_is_migrated_on_disk(tmp_path):
    path = tmp_path.joinpath("system_configuration.yaml")
    shutil.copy2(v51_config_path, path)

    config = SystemConfiguration.load_yaml_file(path, save_backup=True)

    backups = list(tmp_path.glob("system_configuration_v51_*.yaml"))
    assert len(backups) == 1
    assert backups[0].read_text() == v51_config_path.read_text()

    # the migrated file is written back, and reloads through the current-version path:
    reloaded = SystemConfiguration.load_yaml_file(path)
    assert reloaded.version == SystemConfiguration.version
    assert dataclasses.asdict(reloaded) == dataclasses.asdict(config)


def test_v55_renames_are_respected():
    config_text = """
    !SystemConfiguration
    version: 54
    behavior: !BehaviorConfiguration
      ledAlarm: !LEDAlarmConfig
        startIgnoreHour: !Time '17:33:55'
        stopIgnoreHour: !Time '05:42:30'
    """
    cfg = SystemConfiguration.load_yaml(io.StringIO(config_text))
    assert isinstance(cfg, SystemConfiguration)
    assert cfg.behavior.animal_sleep_window == TimePeriod(
        start=datetime.time(17, 33, 55), stop=datetime.time(5, 42, 30))
