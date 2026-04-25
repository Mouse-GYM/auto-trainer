import pytest

from autotrainer.core import Motor
from autotrainer.device import MotorConfigurationFile, StepperConfig, ServoConfig
from autotrainer.device.motor_configuration_file import DEFAULT_TUNNEL_FAN_CONFIG_DCT


@pytest.fixture
def motor_file_cfg_instance():
    return MotorConfigurationFile()


@pytest.fixture
def motor_file_from_empty_dict():
    return MotorConfigurationFile.from_yaml_dict({}, source="pytest")


@pytest.mark.parametrize("cfg_source", ["motor_file_cfg_instance", "motor_file_from_empty_dict"])
def test_it_gets_motor_set_on_construction(request, cfg_source):
    file_cfg = request.getfixturevalue(cfg_source)
    assert isinstance(file_cfg, MotorConfigurationFile)
    for m, motor_cfg in (
        file_cfg.x_config, file_cfg.y_config, file_cfg.z_config,
    ):
        assert isinstance(m, Motor)
        assert m != Motor.NONE
        assert m == motor_cfg.motor
        assert isinstance(motor_cfg, StepperConfig)
    #
    for m, motor_cfg in (
        file_cfg.cover_config,
        file_cfg.load_config,
        file_cfg.tunnel_fan_config,
    ):
        assert isinstance(m, Motor)
        assert m != Motor.NONE
        assert m == motor_cfg.motor
        assert isinstance(motor_cfg, ServoConfig)
    #
    for m, motor_cfg in (
        file_cfg.magnet_config, file_cfg.gate_config,
    ):
        assert isinstance(m, Motor)
        assert m != Motor.NONE
        assert m == motor_cfg.motor
        assert isinstance(motor_cfg, ServoConfig)
    #
    fan_cfg = file_cfg.tunnel_fan_config[1]
    fan_default = ServoConfig.from_dict(DEFAULT_TUNNEL_FAN_CONFIG_DCT)
    fan_default.motor = fan_cfg.motor
    assert fan_cfg == fan_default
