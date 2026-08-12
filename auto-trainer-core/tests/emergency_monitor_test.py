import dataclasses
import logging
import threading
import time
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

    use_daemon = False
    need_explicit_check = True
    desired_set_value = None

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.check_in_progress_event = threading.Event()
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
        self.check_in_progress_event.set()
        desired = self.desired_set_value
        if desired is not None:
            self.desired_set_value = None
            self.is_engaged = desired
        self.check_attempted.set()
        self.check_in_progress_event.clear()


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
        mon.check_done.clear()
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
    assert det.engaged_event.wait(0.4)  # should be very fast
    assert det.is_engaged and mon.is_engaged
    msg = "prevented possible reentrant/deadlock"
    assert (msg in caplog.text) == use_daemon


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


@pytest.mark.parametrize("det1_engage,det2_engage", [[True, False], [False, True]])
@pytest.mark.parametrize("det3_engage", [True, False])
def test_concurrent_reentrant_alarms_engage(
    mon, caplog,
    det1_engage, det2_engage, det3_engage
):
    det1_relax_check = threading.Event()

    class Det1(SimpleDetector):

        use_daemon = True
        need_explicit_check = True

        def _check_state(self) -> Optional[float]:
            # wait to be relaxed while holding this detector lock:
            self.check_in_progress_event.set()
            det1_relax_check.wait(1.5)
            return super()._check_state()

    det1 = Det1()
    det1.desired_set_value = det1_engage
    mon.register_sub_detector("det1", det1)
    assert det1.running
    assert not det1.is_engaged and not mon.is_engaged
    assert det1.check_in_progress_event.wait(0.5)
    assert det1.check_in_progress  # ensure it's in its internal _check_state

    class Det2(SimpleDetector):

        # use_daemon = True
        need_explicit_check = True

        def _check_state(self) -> Optional[float]:
            desired = self.desired_set_value
            if desired is not None:
                det1_relax_check.set()
                det1.check_attempted.wait(1.5)
            super()._check_state()

    class Det3(SimpleDetector):
        need_explicit_check = True

    det2 = Det2()
    det3 = Det3()
    mon.register_sub_detector("det2", det2)
    mon.register_sub_detector("det3", det3)

    assert not mon.is_engaged and not det2.is_engaged and not det3.is_engaged
    caplog.set_level(logging.DEBUG)

    det2.desired_set_value = det2_engage
    det3.desired_set_value = det3_engage
    det1.check_attempted.clear()  # to be sure
    det2.check_attempted.clear()
    det3.check_attempted.clear()
    #
    det2.check_state()

    assert det1.check_attempted.wait(0.5)  # ensure det1 check has been reached, should be very fast
    assert det2.check_attempted.wait(0.5)  # should be very fast
    assert det2.engaged_event.is_set() == det2_engage # can use is_set after given using check_finished.wait before,
        # which is set after is_engaged is set.
    # x, y, z = mon.is_engaged, det1.is_engaged, det2.is_engaged
    assert mon.is_engaged
    assert det1.is_engaged == det1_engage and det2.is_engaged == det2_engage and det3.is_engaged == det3_engage
    # NB: det3 given need_explicit check and don't use daemon is always synced with monitor/emergency.
    assert det1.is_engaged or det2.is_engaged
    exp_reasons = []
    xp_r_add = exp_reasons.append
    if det1_engage:
        xp_r_add("det1")
    if det2_engage:
        xp_r_add("det2")
    if det3_engage:
        xp_r_add("det3")
    assert mon.engaged_reasons == exp_reasons
    msg = "prevented possible reentrant/deadlock check_state to sub-detector"
    assert any(msg in rec.message and (det1.name if det1_engage else det2.name) in str(rec.args) for rec in caplog.records)
    # NB: this asserts that in all the variants of the test case, at least the sub-detector2 was prevented from...
    assert mon.skip_lock_acquire_timeout_msg not in caplog.text  # see BaseDetector.


@pytest.mark.parametrize("use_daemon", [True, False])
@pytest.mark.parametrize("det_cls", [SimpleDetector, GroupSubDetector, AlarmDet])
def test_when_not_using_need_explicit_check(mon, det_cls, use_daemon, caplog):
    r_use_daemon = use_daemon
    class Det(det_cls, BaseDetector):
        default_timer_delay = 60
        need_explicit_check = False
        use_daemon = r_use_daemon

        def check_state(self, *, force: bool=False):
            # NB: "check_state" is executed in/by the caller thread,
            # while "_check_state" will be executed by the daemon thread if it's daemon.
            try:
                super().check_state(force=force)
            finally:
                self.check_attempted.set()  # so set the check_attempted here, too

    det = Det()
    mon.register_sub_detector("det", det)
    assert det.check_attempted.wait(0.5)  # because started
    det.check_attempted.clear()
    assert det.running
    mon.check_done.clear()
    mon.check_state()
    assert mon.check_done.is_set()
    assert not det.check_attempted.is_set()
