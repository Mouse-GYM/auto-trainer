import pytest

from autotrainer.core.configuration.alarm_configuration import EmergencyAlarmConfiguration


def test_alarm_config_constructor():
    not_default = not EmergencyAlarmConfiguration.use_presence_missing_after_exit_tunnel
    cfg = EmergencyAlarmConfiguration(use_presence_missing_after_exit_tunnel=not_default)
    assert cfg.use_presence_missing_after_exit_tunnel == not_default


def test_can_load_previous_config():
    cfg = EmergencyAlarmConfiguration(auto_resume_on_audio_load_cell_thrash_resume="foobar")
    assert isinstance(cfg, EmergencyAlarmConfiguration)


def test_raise_with_positional_arg():
    with pytest.raises(TypeError, match="__init__\(\) takes 1 positional argument but 2 were given"):
        EmergencyAlarmConfiguration("anything")
