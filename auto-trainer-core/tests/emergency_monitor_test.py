import dataclasses
import logging
import threading
from typing import Optional

import pytest

from autotrainer.core.analysis import EmergencyAlarmMonitor
from autotrainer.core.analysis.alarm_detector import AlarmDetector
from autotrainer.core.analysis.detector import BaseDetector, GroupBaseDetector
from autotrainer.core.configuration.alarm_detector import AlarmDetectorConfig
from autotrainer.core.configuration.detector import GroupSubDetectorConfig


@pytest.fixture(autouse=True)
def _use_mock_event_manager(mock_event_manager):
    pass


class Mix:

    need_explicit_check = True
    desired_set_value = None

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.check_attempted = threading.Event()
        self.engaged_event = threading.Event()
        disengaged_e = self.disengaged_event = threading.Event()
        disengaged_e.set()

    def set_is_engaged(self, engaged):
        super().set_is_engaged(engaged)  # noqa
        if self.is_engaged:
            self.engaged_event.set()
            self.disengaged_event.clear()
        else:
            self.disengaged_event.set()
            self.engaged_event.clear()

    def _check_state(self) -> Optional[float]:
        desired = self.desired_set_value
        if desired is not None:
            self.desired_set_value = None
            self.is_engaged = desired
        self.check_attempted.set()


@dataclasses.dataclass()
class DefaultEmergencyAlarmDetectorConfig(AlarmDetectorConfig):
    is_emergency_condition: bool = True


class AlarmDet(Mix, AlarmDetector[DefaultEmergencyAlarmDetectorConfig]):
    config_cls = DefaultEmergencyAlarmDetectorConfig


class SimpleDetector(Mix, BaseDetector):
    pass


class GroupSubDetector(Mix, BaseDetector[GroupSubDetectorConfig]):
    config_cls = GroupSubDetectorConfig


class Mon(EmergencyAlarmMonitor):
    use_daemon = False  # ensure

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.check_done = threading.Event()

    def _check_state(self, *, force: bool=False) -> Optional[float]:
        super()._check_state(force=force)
        self.check_done.set()


@pytest.fixture()
def mon():
    mon = Mon()
    try:
        mon.restart()
        yield mon
    finally:
        for det in mon.sub_detectors.values():
            det.stop()
        mon.stop()


@pytest.fixture()
def caplog(caplog):
    caplog.set_level(logging.DEBUG)
    return caplog


@pytest.mark.parametrize("use_daemon", [True, False])
@pytest.mark.parametrize("det_cls", [SimpleDetector, GroupSubDetector, AlarmDet])
def test_monitor_engage_from_itself(mon, det_cls, use_daemon, caplog):
    det = det_cls()
    det.use_daemon = use_daemon
    mon.register_sub_detector("det", det)
    mon.check_state()
    assert not mon.is_engaged
    caplog.set_level(logging.DEBUG)
    det.desired_set_value = True
    assert not det.is_engaged
    det.check_attempted.clear()
    det.engaged_event.clear()
    mon.check_state()
    # assert det.check_attempted.wait(0.3)
    assert det.engaged_event.wait(0.2)  # should be very fast
    assert det.is_engaged and mon.is_engaged
    msg = "prevented possible reentrant/deadlock"
    if use_daemon:
        assert msg in caplog.text
    else:
        assert msg not in caplog.text


@pytest.mark.parametrize("need_explicit_check", [True, False])
@pytest.mark.parametrize("use_daemon", [True, False])
@pytest.mark.parametrize("det_cls", [SimpleDetector, GroupSubDetector, AlarmDet])
def test_monitor_engage_from_detector(mon, det_cls, use_daemon, need_explicit_check, caplog):
    det = det_cls()
    det: BaseDetector
    det.need_explicit_check = need_explicit_check
    det.use_daemon = use_daemon
    mon.register_sub_detector("det", det)
    mon.check_state()
    assert not mon.is_engaged
    det.check_attempted.clear()
    det.desired_set_value = True
    det.check_state()
    assert det.engaged_event.wait(0.2)  # should be very fast
    assert det.is_engaged and mon.is_engaged
    msg = "prevented possible reentrant/deadlock"
    if need_explicit_check:
        assert msg in caplog.text
    else:
        assert msg not in caplog.text


@pytest.mark.parametrize("det_cls", [AlarmDet, GroupSubDetector])
def test_with_use(mon, det_cls, caplog):
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
    assert "prevented possible reentrant/deadlock" not in caplog.text


@pytest.mark.parametrize("use_daemon", [False, True])
@pytest.mark.parametrize("update_method", ["det", "mon", "det_cfg"])
def test_is_emergency_cond(mon, use_daemon, update_method):
    det = AlarmDet()
    #
    if update_method == "det":
        update = det.check_state
    elif update_method == "det_cfg":
        update = det.update_config
    else:
        update = mon.check_state
    #
    det.use_daemon = use_daemon
    det.config.is_emergency_condition = False
    mon.register_sub_detector("det", det)
    det.desired_set_value = True
    update()
    assert det.engaged_event.wait(0.2)
    assert det.is_engaged and not mon.is_engaged
    det.config.is_emergency_condition = True
    mon.check_state()
    assert det.is_engaged and mon.is_engaged
    det.check_attempted.clear()
    det.desired_set_value = False
    update()
    assert det.check_attempted.wait(0.2)
    assert not det.is_engaged and not mon.is_engaged


@pytest.mark.parametrize("det_cls", [AlarmDet, GroupSubDetector])
@pytest.mark.parametrize("update_method", ["det", "mon", "det_cfg"])
def test_allow_autoresume(mon, det_cls, update_method):
    det = det_cls()
    if update_method == "det":
        update = det.check_state
    elif update_method == "det_cfg":
        update = det.update_config
    else:
        update = mon.check_state
    #
    det.config.allow_autoresume_on_cleared = False
    mon.register_sub_detector("det", det)
    det.desired_set_value = True
    update()
    det.engaged_event.wait(0.2)
    assert det.is_engaged and mon.is_engaged
    det.desired_set_value = False
    det.check_attempted.clear()
    update()
    assert det.check_attempted.wait(0.2)
    assert not det.is_engaged and mon.is_engaged
    det.check_attempted.clear()
    # now, only update config:
    det.config.allow_autoresume_on_cleared = True
    det.update_config()  # this is what actually always ensures emergency monitor check_state is actually called.
    # and should always be used after a detector config change. rather than any possible other _update()_.
    assert det.check_attempted.wait(0.2)
    assert not det.is_engaged and not mon.is_engaged


@pytest.mark.parametrize("det1_use_daemon", [True, False])
@pytest.mark.parametrize("det2_use_daemon", [True, False])
@pytest.mark.parametrize("det2_engage", [True, False])
def test_concurrent_reentrant_alarms_engage(
    mon, caplog,
    det1_use_daemon, det2_use_daemon, det2_engage,
):
    det1_relax_check = threading.Event()

    class Det1(SimpleDetector):

        use_daemon = det1_use_daemon
        need_explicit_check = True

        def _check_state(self) -> Optional[float]:
            det1_relax_check.wait()
            return super()._check_state()

    det1 = Det1()
    if not det1_use_daemon:
        det1.check_state = lambda f=False: None
        det1.start()
        del det1.check_state
    det1.desired_set_value = True
    mon.register_sub_detector("det1", det1)
    assert det1.running
    assert not det1.is_engaged and not mon.is_engaged

    class Det2(SimpleDetector):

        use_daemon = det2_use_daemon
        need_explicit_check = True

        def _check_state(self) -> Optional[float]:
            desired = self.desired_set_value
            if desired is not None:
                det1_relax_check.set()
                if not det1_use_daemon and not det2_engage:
                    det1.check_state()
            super()._check_state()
            if desired is not None:
                det1.check_attempted.wait(5)

    det2 = Det2()
    mon.register_sub_detector("det2", det2)
    assert not mon.is_engaged and not det2.is_engaged
    caplog.set_level(logging.DEBUG)

    det2.desired_set_value = det2_engage
    det2.check_attempted.clear()
    # if not det2_use_daemon:
    det2.check_state()

    assert det1.engaged_event.wait(0.5)  # should be very fast
    assert det2.check_attempted.wait(0.5)
    if det2_engage:
        assert det2.engaged_event.wait(0.5)
    # assert det2.check_attempted.wait(0.5)
    # x, y, z = mon.is_engaged, det1.is_engaged, det2.is_engaged
    # mon.stop()
    assert mon.is_engaged and det1.is_engaged and det2.is_engaged is det2_engage
    assert mon.engaged_reasons == (["det1", "det2"] if det2_engage
                                   else ["det1"])
    assert "could not acquire lock" not in caplog.text
    assert "prevented possible reentrant/deadlock check_state to sub-detector" in caplog.text


@pytest.mark.parametrize("use_daemon", [True, False])
@pytest.mark.parametrize("det_cls", [SimpleDetector, GroupSubDetector, AlarmDet])
def test_when_not_using_need_explicit_check(mon, det_cls, use_daemon, caplog):
    r_use_daemon = use_daemon
    class Det(det_cls, BaseDetector):
        default_timer_delay = 60
        need_explicit_check = False
        use_daemon = r_use_daemon
        check_attempted = threading.Event()

        def check_state(self, *, force: bool=False):
            super().check_state(force=force)
            self.check_attempted.set()

    det = Det()
    mon.register_sub_detector("det", det)
    det.check_attempted.wait(1)  # because started
    det.check_attempted.clear()
    assert det.running
    mon.check_state()
    assert mon.check_done.is_set()
    assert not det.check_attempted.is_set()
