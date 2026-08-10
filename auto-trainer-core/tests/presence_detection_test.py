
import dataclasses
import math

import pytest

from autotrainer.core.configuration.presence_detection_configuration import PresenceDetectionConfig
from autotrainer.core.video_detection import PresenceDetectionAttrs


def modify_value(value):
    if isinstance(value, bool):
        return not value
    elif isinstance(value, float):
        if math.isinf(value):
            return -value
        elif math.isfinite(value):
            return value + 5
        else:
            return 42
    return object()


@pytest.mark.parametrize("field", [f.name.lstrip('_') for f in dataclasses.fields(PresenceDetectionAttrs)])
def test_to_local_value(field):
    det = PresenceDetectionAttrs()
    det2 = det.to_local_value()
    det3 = det.to_local_value()
    assert det == det2 == det3
    val = getattr(det, field)
    new_val = modify_value(val)
    setattr(det, field, new_val)
    assert det != det2
    assert det2 == det3
    setattr(det2, field, new_val)
    assert det == det2 and det2 != det3
    assert getattr(det3, field) == val
    setattr(det3, field, new_val)
    det4 = det3.to_local_value()
    assert det4 == det3 == det2 == det


@pytest.mark.parametrize("field", [f.name for f in dataclasses.fields(PresenceDetectionConfig)])
def test_load_save_config(field):
    attrs = PresenceDetectionAttrs()
    attrs2 = attrs.to_local_value()
    cfg = attrs.to_config()
    value = getattr(cfg, field)
    attrs2.load_config(cfg)
    assert getattr(attrs, field) == value == getattr(attrs2, field)
    assert attrs2.to_config() == cfg
    new_value = modify_value(value)
    setattr(cfg, field, new_value)
    attrs2.load_config(cfg)
    after_cfg = attrs2.to_config()
    assert after_cfg == cfg
    assert after_cfg != attrs.to_config()
