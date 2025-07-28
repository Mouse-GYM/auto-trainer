from pathlib import Path

import yaml

from autotrainer.core import SystemConfiguration, CameraId


fixtures_path = Path(__file__).parent.joinpath("fixtures")

v0_config_path = fixtures_path.joinpath("v0_config.yaml")
v1_config_path = fixtures_path.joinpath("v1_config.yaml")


def _confirm_values(configuration: SystemConfiguration, version: int):
    assert configuration.version == version

    assert len(configuration.cameras) == 3
    cam0 = configuration.cameras[0]
    assert cam0.id == CameraId.Left
    assert cam0.name == "left"
    assert cam0.is_enabled is True
    assert cam0.is_record_enabled is True
    assert cam0.record_mode == 1
    assert cam0.is_still_image_capture_enabled is True
    assert cam0.still_image_capture_interval == 10.5
    assert cam0.scheme == "random"
    assert cam0.host == "0"
    assert cam0.port == 0
    assert cam0.path == ""
    assert cam0.params.get("width", -1) == 300
    assert cam0.params.get("height", -1) == 200

    assert configuration.cameras[1].id == CameraId.Right
    assert configuration.cameras[2].id == CameraId.Web

    assert configuration.hardware.tunnel_identifier == "COM24"
    assert configuration.hardware.pellet_identifier == "COM28"

    assert configuration.inference.pose_model_location == "/home/autotrainer/models/current-model-2000-01-02"
    assert configuration.inference.is_enabled is True
    assert configuration.inference.intersession_wait_time == 1.0

    assert configuration.behavior.pellet_delivery.is_enabled is True
    assert configuration.behavior.pellet_delivery.is_pellet_cover_enabled is True
    assert configuration.behavior.pellet_delivery.is_intersession_analysis_enabled is True
    assert configuration.behavior.pellet_delivery.max_pellets_per_session == 20
    assert configuration.behavior.pellet_delivery.max_pellets_per_day == 25
    assert configuration.behavior.pellet_delivery.max_pellet_missing_seconds == 10.0

    assert configuration.behavior.head_clamp.min_baseline_intensity == 5.0
    assert configuration.behavior.head_clamp.max_baseline_intensity == 80.0
    assert configuration.behavior.head_clamp.baseline_intensity_increment == 15.0
    assert configuration.behavior.head_clamp.auto_clamp_intensity == 80
    assert configuration.behavior.head_clamp.auto_clamp_release_tone_freq == 6000
    assert configuration.behavior.head_clamp.auto_clamp_release_tone_delay == 0.2

    assert configuration.behavior.load_cell.weight_active_threshold == 10
    assert configuration.behavior.load_cell.threshold_duration == 0.20
    assert configuration.behavior.load_cell.min_event_duration == 4.0
    assert configuration.behavior.load_cell.min_post_event_hold_duration == 3.0

    assert configuration.behavior.headbar_pressure.threshold == 10
    assert configuration.behavior.headbar_pressure.duration == 1.5

    assert configuration.behavior.auto_tare.threshold == 1.1
    assert configuration.behavior.auto_tare.duration == 1.0
    assert configuration.behavior.auto_tare.range_threshold == 1.75

    assert configuration.persistence.output_location == "/home/autotrainer/output"


def test_load_version_zero():
    # All the values in this file are different from the defaults, when originally written.
    configuration = SystemConfiguration.load_yaml_file(v0_config_path, save_backup=False)
    _confirm_values(configuration, SystemConfiguration.version)


def test_round_trip():
    # Load from a version 0 file and assert that is not a SystemConfiguration dump w/YAML tags.
    # Dump from SystemConfiguration and assert that it is a SystemConfiguration dump w/YAML tags and subsequent load
    #     will go through the SystemConfiguration custom loader.
    # Load that output and verify values

    # Bypass SystemConfiguration.load_file to allow the first assertion.
    with v0_config_path.open() as fh:
        file_content = fh.read()
        assert file_content.find("!SystemConfiguration") == -1
        fh.seek(0)
        configuration = SystemConfiguration.load_yaml(file_content)

    saved = configuration.dump_yaml()
    assert saved.find("!SystemConfiguration") != -1

    loaded = SystemConfiguration.load_yaml(saved)
    _confirm_values(loaded, SystemConfiguration.version)


def test_load_version_1():
    # All the values in this file are different from the defaults, when originally written.
    path = fixtures_path.joinpath("v1_config.yaml")
    with path.open() as fh:
        config = SystemConfiguration.load_yaml(fh)
    assert len(config.cameras) == 3
    cam0 = config.cameras[0]
    assert cam0.id is CameraId.Left
    assert cam0.name == "left"
    assert cam0.host is None
    assert cam0.port == 0
    assert cam0.is_enabled is True
    assert cam0.params == dict(
        fps=150,
        width=256,
        height=256,
    )
    #
    behavior = config.behavior
    assert behavior.pellet_delivery.is_enabled is False
    assert behavior.pellet_delivery.is_pellet_cover_enabled is True
    assert behavior.pellet_delivery.max_pellets_per_day == 75
    load_cell = behavior.load_cell
    assert load_cell.weight_active_threshold == 15
    assert load_cell.threshold_duration == 0.25
    assert load_cell.min_event_duration == 3
    assert load_cell.min_post_event_hold_duration == 6
    #
    assert config.persistence.output_location == "/output_location_path"
