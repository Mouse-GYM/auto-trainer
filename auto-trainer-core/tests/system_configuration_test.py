import dataclasses
import io
from pathlib import Path

import pytest
import yaml

from autotrainer.core import SystemConfiguration, CameraId, HardwareConfiguration, InferenceConfiguration
from autotrainer.core.analysis import LoadCellConfiguration, HeadbarPressureConfiguration, LoadCellAutoTareConfiguration
from autotrainer.core.configuration.behavior_configuration import PelletDeliveryConfiguration, HeadClampConfiguration

fixtures_path = Path(__file__).parent.joinpath("fixtures")

v0_config_path = fixtures_path.joinpath("v0_config.yaml")
v1_config_path = fixtures_path.joinpath("v1_config.yaml")


v0_expected_result_config = {'version': 2,
 'cameras': [{'id': CameraId.Left,
   'name': 'left',
   'is_enabled': True,
   'is_record_enabled': True,
   'record_mode': 1,
   'is_still_image_capture_enabled': True,
   'still_image_capture_interval': 10.5,
   'scheme': 'random',
   'host': '0',
   'port': 0,
   'path': '',
   'params': {'width': 300, 'height': 200}},
  {'id': CameraId.Right,
   'name': 'right',
   'is_enabled': True,
   'is_record_enabled': True,
   'record_mode': 1,
   'is_still_image_capture_enabled': False,
   'still_image_capture_interval': 0.0,
   'scheme': 'random',
   'host': '0',
   'port': 0,
   'path': '',
   'params': {'width': 300, 'height': 200}},
  {'id': CameraId.Web,
   'name': 'Random Image',
   'is_enabled': True,
   'is_record_enabled': False,
   'record_mode': 0,
   'is_still_image_capture_enabled': False,
   'still_image_capture_interval': 0.0,
   'scheme': 'random',
   'host': '0',
   'port': 0,
   'path': '',
   'params': {'width': 300, 'height': 200}}],
 'hardware': {'tunnel_identifier': 'COM24', 'pellet_identifier': 'COM28'},
 'inference': {'pose_model_location': '/home/autotrainer/models/current-model-2000-01-02',
  'is_enabled': True,
  'intersession_wait_time': 1.0},
 'behavior': {'pellet_delivery': {'is_enabled': True,
   'is_pellet_cover_enabled': True,
   'is_intersession_analysis_enabled': True,
   'max_pellets_per_session': 20,
   'max_pellets_per_day': 25,
   'max_pellet_missing_seconds': 10.0},
  'head_clamp': {'min_baseline_intensity': 5.0,
   'max_baseline_intensity': 80.0,
   'baseline_intensity_increment': 15.0,
   'auto_clamp_intensity': 80,
   'auto_clamp_release_tone_freq': 6000,
   'auto_clamp_release_tone_delay': 0.2},
  'load_cell': {'weight_active_threshold': 10,
   'weight_inactive_threshold': 5,
   'threshold_duration': 0.2,
   'min_event_duration': 4.0,
   'min_post_event_hold_duration': 3.0,
   'thrashing_var_weight_threshold_min': 20,
   'thrashing_var_weight_threshold_max': 30,
   'thrashing_var_min_delay': 0.05,
   'thrashing_var_max_delay': 0.2,
   'thrashing_min_ptp_change_count': 3},
  'headbar_pressure': {'threshold': 10, 'duration': 1.5},
  'auto_tare': {'threshold': 1.1, 'range_threshold': 1.75, 'duration': 1.0}},
 'persistence': {'output_location': '/home/autotrainer/output'}}


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
    assert dataclasses.asdict(config) == {
        'behavior': {'auto_tare': {'duration': 2.0,
                                   'range_threshold': 0.75,
                                   'threshold': 0.1},
                     'head_clamp': {'auto_clamp_intensity': 100,
                                    'auto_clamp_release_tone_delay': 0.1,
                                    'auto_clamp_release_tone_freq': 7000,
                                    'baseline_intensity_increment': 10.0,
                                    'max_baseline_intensity': 90.0,
                                    'min_baseline_intensity': 0.0},
                     'headbar_pressure': {'duration': 0.5, 'threshold': 20},
                     'load_cell': {'min_event_duration': 3.0,
                                   'min_post_event_hold_duration': 6.0,
                                   'thrashing_min_ptp_change_count': 3,
                                   'thrashing_var_max_delay': 0.2,
                                   'thrashing_var_min_delay': 0.05,
                                   'thrashing_var_weight_threshold_max': 30,
                                   'thrashing_var_weight_threshold_min': 20,
                                   'threshold_duration': 0.25,
                                   'weight_active_threshold': 15.0,
                                   'weight_inactive_threshold': 5},
                     'pellet_delivery': {'is_enabled': False,
                                         'is_intersession_analysis_enabled': True,
                                         'is_pellet_cover_enabled': True,
                                         'max_pellet_missing_seconds': 15.0,
                                         'max_pellets_per_day': 75,
                                         'max_pellets_per_session': 10}},
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
                     'scheme': 'playback',
                     'still_image_capture_interval': 0.0}],
        'hardware': {'pellet_identifier': '/dev/ttyS31',
                     'tunnel_identifier': '/dev/ttyS30'},
        'inference': {'intersession_wait_time': 2.0,
                      'is_enabled': True,
                      'pose_model_location': '/pose_model_path'},
        'persistence': {'output_location': '/output_location_path'},
        'version': 2}


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
    assert dataclasses.asdict(cfg) == {
        # apart the version and persistence.output_location, these are all the defaults values
         'version': 3,
         'cameras': [],
         'hardware': {'tunnel_identifier': HardwareConfiguration.tunnel_identifier,
                      'pellet_identifier': HardwareConfiguration.pellet_identifier},
         'inference': {'pose_model_location': InferenceConfiguration.pose_model_location,
          'is_enabled': InferenceConfiguration.is_enabled,
          'intersession_wait_time': InferenceConfiguration.intersession_wait_time},
         'behavior': {'pellet_delivery': {'is_enabled': PelletDeliveryConfiguration.is_enabled,
           'is_pellet_cover_enabled': PelletDeliveryConfiguration.is_pellet_cover_enabled,
           'is_intersession_analysis_enabled': PelletDeliveryConfiguration.is_intersession_analysis_enabled,
           'max_pellets_per_session': PelletDeliveryConfiguration.max_pellets_per_session,
           'max_pellets_per_day': PelletDeliveryConfiguration.max_pellets_per_day,
           'max_pellet_missing_seconds': PelletDeliveryConfiguration.max_pellet_missing_seconds},
          'head_clamp': {'min_baseline_intensity': HeadClampConfiguration.min_baseline_intensity,
           'max_baseline_intensity': HeadClampConfiguration.max_baseline_intensity,
           'baseline_intensity_increment': HeadClampConfiguration.baseline_intensity_increment,
           'auto_clamp_intensity': HeadClampConfiguration.auto_clamp_intensity,
           'auto_clamp_release_tone_freq': HeadClampConfiguration.auto_clamp_release_tone_freq,
           'auto_clamp_release_tone_delay': HeadClampConfiguration.auto_clamp_release_tone_delay},
          'load_cell': {'weight_active_threshold': LoadCellConfiguration.weight_active_threshold,
           'weight_inactive_threshold': LoadCellConfiguration.weight_inactive_threshold,
           'threshold_duration': LoadCellConfiguration.threshold_duration,
           'min_event_duration': LoadCellConfiguration.min_event_duration,
           'min_post_event_hold_duration': LoadCellConfiguration.min_post_event_hold_duration,
           'thrashing_var_weight_threshold_min': LoadCellConfiguration.thrashing_var_weight_threshold_min,
           'thrashing_var_weight_threshold_max': LoadCellConfiguration.thrashing_var_weight_threshold_max,
           'thrashing_var_min_delay': LoadCellConfiguration.thrashing_var_min_delay,
           'thrashing_var_max_delay': LoadCellConfiguration.thrashing_var_max_delay,
           'thrashing_min_ptp_change_count': LoadCellConfiguration.thrashing_min_ptp_change_count},
          'headbar_pressure': {'threshold': HeadbarPressureConfiguration.threshold, 'duration': HeadbarPressureConfiguration.duration},
          'auto_tare': {'threshold': LoadCellAutoTareConfiguration.threshold,
                        'range_threshold': LoadCellAutoTareConfiguration.range_threshold,
                        'duration': LoadCellAutoTareConfiguration.duration}},
         'persistence': {'output_location': '/output_location_path'}}
