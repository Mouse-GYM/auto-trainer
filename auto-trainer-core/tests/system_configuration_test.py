from pathlib import Path

import yaml

from autotrainer.core import SystemConfiguration, CameraId


def _confirm_values(configuration: SystemConfiguration, version: int):
    assert configuration.version == version

    assert len(configuration.cameras) == 3
    assert configuration.cameras[0].id == CameraId.Left
    assert configuration.cameras[0].name == "Random Image"
    assert configuration.cameras[0].is_enabled is True
    assert configuration.cameras[0].is_record_enabled is True
    assert configuration.cameras[0].record_mode == 1
    assert configuration.cameras[0].is_still_image_capture_enabled is True
    assert configuration.cameras[0].still_image_capture_interval == 10.5
    assert configuration.cameras[0].scheme == "random"
    assert configuration.cameras[0].host == "0"
    assert configuration.cameras[0].port == 0
    assert configuration.cameras[0].path == ""
    assert configuration.cameras[0].params.get("width", -1) == 300
    assert configuration.cameras[0].params.get("height", -1) == 200

    assert configuration.cameras[1].id == CameraId.Right
    assert configuration.cameras[2].id == CameraId.Web

    assert configuration.hardware.tunnel_identifier == "COM24"
    assert configuration.hardware.pellet_identifier == "COM28"

    assert configuration.inference.pose_model_location == r"/home/autotrainer/models/current-model-2000-01-02"
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

    assert configuration.persistence.output_location == r"/home/autotrainer/output"


def test_load_version_zero():
    # All the values in this file are different from the defaults, when originally written.
    path = Path(__file__).parent.joinpath("fixtures").joinpath("version_zero_configuration.yaml")

    configuration = SystemConfiguration.load_yaml_file(path)

    _confirm_values(configuration, 1)


def test_round_trip():
    path = Path(__file__).parent.joinpath("fixtures").joinpath("version_zero_configuration.yaml")

    # Load from a version 0 file and assert that is not a SystemConfiguration dump w/YAML tags.
    # Dump from SystemConfiguration and assert that it is a SystemConfiguration dump w/YAML tags and subsequent load
    #     will go through the SystemConfiguration custom loader.
    # Load that output and verify values

    # Bypass SystemConfiguration.load_file to allow the first assertion.
    with open(path, 'r') as file_contents:
        assert str(file_contents).find("!SystemConfiguration") == -1
        configuration = SystemConfiguration.load_yaml(file_contents)

    saved = configuration.dump_yaml()

    assert saved.find("!SystemConfiguration") != -1

    loaded = SystemConfiguration.load_yaml(saved)

    _confirm_values(loaded, 1)


if __name__ == '__main__':
    test_load_version_zero()
    test_round_trip()
