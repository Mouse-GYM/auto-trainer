import pytest

from autotrainer.core.configuration.alarm_configuration import EmergencyAlarmConfiguration


def test_raise_with_positional_arg():
    with pytest.raises(TypeError, match=r"__init__\(\) takes 1 positional argument but 2 were given"):
        EmergencyAlarmConfiguration("anything")  # noqa


def test_with_non_defaults():
    cfg = EmergencyAlarmConfiguration(animal_thrashing="foobar")  # noqa
    assert cfg.animal_thrashing == "foobar"
