import dataclasses
from typing import Optional

import pytest

from autotrainer.core.analysis import EmergencyAlarmMonitor
from autotrainer.core.analysis.alarm_detector import AlarmDetector
from autotrainer.core.analysis.detector import BaseDetector, GroupBaseDetector
from autotrainer.core.configuration.alarm_detector import AlarmDetectorConfig
from autotrainer.core.configuration.detector import GroupSubDetectorConfig


class Mix:

    need_explicit_check = True
    desired_set_value = None

    def _check_state(self) -> Optional[float]:
        desired = self.desired_set_value
        if desired is not None:
            self.desired_set_value = None
            self.is_engaged = desired


@dataclasses.dataclass()
class DefaultEmergencyAlarmDetectorConfig(AlarmDetectorConfig):
    is_emergency_condition: bool = True


class AlarmDet(Mix, AlarmDetector[DefaultEmergencyAlarmDetectorConfig]):
    config_cls = DefaultEmergencyAlarmDetectorConfig


class SimpleDetector(Mix, BaseDetector):
    pass


class GroupSubDetector(Mix, BaseDetector[GroupSubDetectorConfig]):
    config_cls = GroupSubDetectorConfig


@pytest.fixture()
def mon():
    mon = EmergencyAlarmMonitor()
    mon.use_daemon = False
    try:
        mon.restart()
        yield mon
    finally:
        mon.stop()


@pytest.mark.parametrize("det_cls", [SimpleDetector, GroupSubDetector, AlarmDet])
def test_detector_engage(mon, det_cls):
    det = det_cls()
    mon.register_sub_detector("det", det)
    mon.check_state()
    assert not mon.is_engaged
    det.desired_set_value = True
    assert not det.is_engaged
    mon.check_state()
    assert det.is_engaged and mon.is_engaged


@pytest.mark.parametrize("det_cls", [AlarmDet, GroupSubDetector])
def test_with_use(mon, det_cls):
    det = det_cls()
    det.config.use = True
    mon.register_sub_detector("det", det)
    det.desired_set_value = True
    mon.check_state()
    assert det.is_engaged and mon.is_engaged
    det.is_engaged = False
    assert not det.is_engaged and not mon.is_engaged
    det.desired_set_value = True
    det.config.use = False
    mon.check_state()
    assert det.is_engaged and not mon.is_engaged


def test_is_emergency_cond(mon):
    det = AlarmDet()
    det.config.is_emergency_condition = False
    mon.register_sub_detector("det", det)
    det.desired_set_value = True
    mon.check_state()
    assert det.is_engaged and not mon.is_engaged
    det.config.is_emergency_condition = True
    mon.check_state()
    assert det.is_engaged and mon.is_engaged
    det.desired_set_value = False
    mon.check_state()
    assert not det.is_engaged and not mon.is_engaged


@pytest.mark.parametrize("det_cls", [AlarmDet, GroupSubDetector])
def test_allow_autoresume(mon, det_cls):
    det = det_cls()
    det.config.allow_autoresume_on_cleared = False
    mon.register_sub_detector("det", det)
    det.desired_set_value = True
    mon.check_state()
    assert det.is_engaged and mon.is_engaged
    det.desired_set_value = False
    mon.check_state()
    assert not det.is_engaged and mon.is_engaged
    det.config.allow_autoresume_on_cleared = True
    mon.check_state()
    assert not det.is_engaged and not mon.is_engaged
