from typing import Optional

import pytest

from autotrainer.core import get_perf_now
from autotrainer.core.analysis.watchdog_monitor import WatchdogMonitor
from top_fixtures import increase_simulate_perf_now


@pytest.fixture
def watchdog_mon(mock_get_perf_now) -> WatchdogMonitor:  # noqa
    mon = WatchdogMonitor()
    try:
        yield mon  # noqa
    finally:
        mon.stop()


@pytest.mark.parametrize("start_perf_c", [None, "get_perf_now"])
@pytest.mark.parametrize("timeout_trigger", [5, 15])
def test_normal_watchdog_item(watchdog_mon, timeout_trigger, start_perf_c):
    if start_perf_c == "get_perf_now":
        start_perf_c = get_perf_now()
    start_perf_c: Optional[float]
    mon = watchdog_mon
    cfg = mon.config
    cfg.timeout_trigger_delay = timeout_trigger
    def mon_check():
        mon.check_state(force=True)
    assert len(mon.sub_detectors) == 0
    assert not mon.is_engaged
    w1_perf_c = start_perf_c
    def watch1():
        return w1_perf_c
    mon.register_watchdog(watch1.__name__, watch1)
    det = mon.get_sub_detector(watch1.__name__)
    assert det is not None
    assert len(mon.sub_detectors) == 1
    mon_check()
    assert not mon.is_engaged and not det.is_engaged
    w1_perf_c = get_perf_now()
    mon_check()
    assert not mon.is_engaged and not det.is_engaged
    increase_simulate_perf_now(cfg.timeout_trigger_delay / 2)
    mon_check()
    assert not mon.is_engaged and not det.is_engaged
    increase_simulate_perf_now(cfg.timeout_trigger_delay / 2)
    mon_check()
    assert mon.is_engaged and det.is_engaged
    w1_perf_c = get_perf_now()
    mon_check()
    assert not mon.is_engaged and not det.is_engaged
    # retrigger it :
    increase_simulate_perf_now(cfg.timeout_trigger_delay)
    mon_check()
    assert mon.is_engaged and det.is_engaged
    mon.unregister_watchdog(watch1.__name__)
    mon_check()
    assert not mon.is_engaged and det.is_engaged, \
        "after unregister and new mon check_state the watchdog mon is disengaged but the detector is still engaged"


def test_with_2_watchdogs(watchdog_mon):
    mon = watchdog_mon
    cfg = mon.config
    def mon_check():
        mon.check_state(force=True)
    assert len(mon.sub_detectors) == 0
    assert not mon.is_engaged
    w1_perf_c = get_perf_now()
    def watch1():
        return w1_perf_c
    w2_perf_c = get_perf_now()
    def watch2():
        return w2_perf_c
    assert len(mon.sub_detectors) == 0
    mon.register_watchdog(watch1.__name__, watch1)
    assert len(mon.sub_detectors) == 1
    mon.register_watchdog(watch2.__name__, watch2)
    assert len(mon.sub_detectors) == 2
    mon_check()
    assert not mon.is_engaged
    increase_simulate_perf_now(cfg.timeout_trigger_delay / 2)
    mon_check()
    assert not mon.is_engaged
    increase_simulate_perf_now(1 + cfg.timeout_trigger_delay / 2)
    mon_check()
    assert mon.is_engaged
    assert mon.engaged_watchdogs == mon.engaged_reasons == [watch1.__name__, watch2.__name__]
    #
    det1 = mon.get_sub_detector(watch1.__name__)
    assert det1 is not None
    det1.config.use = False
    mon_check()
    assert mon.is_engaged
    assert mon.engaged_watchdogs == mon.engaged_reasons == [watch2.__name__]
    det1.config.use = True
    #
    w1_perf_c = get_perf_now()
    mon_check()
    assert mon.is_engaged
    assert mon.engaged_watchdogs == mon.engaged_reasons == [watch2.__name__]
    w2_perf_c = get_perf_now()
    mon_check()
    assert not mon.is_engaged


def test_without_allow_resume(watchdog_mon):
    mon = watchdog_mon
    cfg = mon.config
    def mon_check():
        mon.check_state(force=True)
    assert len(mon.sub_detectors) == 0
    assert not mon.is_engaged
    w1_perf_c = get_perf_now()
    def watch1():
        return w1_perf_c
    mon.register_watchdog(watch1.__name__, watch1)
    det = mon.get_sub_detector(watch1.__name__)
    assert det is not None
    mon_check()
    assert not det.is_engaged and not mon.is_engaged
    det.config.allow_autoresume_on_cleared = False
    increase_simulate_perf_now(cfg.timeout_trigger_delay)
    mon_check()
    assert det.is_engaged and mon.is_engaged
    w1_perf_c = get_perf_now()
    mon_check()
    assert not det.is_engaged and mon.is_engaged, "watchdog monitor keeps engaged despite watchdog item recovered"
    assert mon.engaged_watchdogs == [watch1.__name__]
    #
    det.config.allow_autoresume_on_cleared = True
    mon_check()
    assert not det.is_engaged and not mon.is_engaged and mon.engaged_watchdogs == []
