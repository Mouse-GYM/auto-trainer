import datetime
from unittest import mock

import pytest
from autotrainer.core.analysis import system_maintenance_alarm
from autotrainer.core.analysis.system_maintenance_alarm import SystemMaintenanceAlarm


@pytest.fixture
def maint():
    mon = SystemMaintenanceAlarm()
    mon.use_daemon = False  # use sync mode, easier test
    mon.start()
    try:
        yield mon
    finally:
        mon.stop()


def test_max_pellet_loaded(maint: SystemMaintenanceAlarm):
    cfg = maint.config
    maint.update_pellet_loaded(cfg.max_pellets_loaded_count + 1)
    assert maint.is_engaged
    assert maint.max_pellet_loaded_engaged
    maint.update_pellet_loaded(0)
    assert not maint.is_engaged
    assert not maint.max_pellet_loaded_engaged
    cfg.use_max_pellet_loaded = False
    maint.update_pellet_loaded(cfg.max_pellets_loaded_count + 1)
    assert not maint.is_engaged
    assert maint.max_pellet_loaded_engaged


def test_max_consecutive_failed_load(maint: SystemMaintenanceAlarm):
    cfg = maint.config
    maint.update_failed_pellet_load(consecutive=cfg.max_consecutive_failed_loaded)
    assert maint.is_engaged
    assert maint.max_consecutive_failed_load_engaged
    maint.update_failed_pellet_load(consecutive=0)
    assert not maint.is_engaged
    assert not maint.max_consecutive_failed_load_engaged
    cfg.use_max_consecutive_failed_load = False
    maint.update_failed_pellet_load(consecutive=cfg.max_consecutive_failed_loaded)
    assert not maint.is_engaged
    assert maint.max_consecutive_failed_load_engaged


def test_cage_need_clean(maint: SystemMaintenanceAlarm):
    cfg = maint.config
    cfg.cage_need_clean_look_ahead_hours = 0  # for exact
    # and not having test failed if executed less than that before midnight.
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    maint.set_cage_clean_next_day(yesterday)
    assert maint.is_engaged
    assert maint.cage_need_clean_engaged
    maint.set_cage_clean_next_day(today + datetime.timedelta(days=1))  # requires look_ahead_hours = 0
    # otherwise test fails if executed less than that before midnight.
    assert not maint.is_engaged
    assert not maint.cage_need_clean_engaged
    cfg.use_cage_need_clean = False
    maint.set_cage_clean_next_day(yesterday)
    assert not maint.is_engaged
    assert maint.cage_need_clean_engaged


def test_look_ahead_hours_with_cage_need_clean(maint: SystemMaintenanceAlarm, monkeypatch):
    cfg = maint.config
    mid_day = datetime.datetime.today().replace(hour=12, minute=0, second=0, microsecond=0)
    tomorrow = (mid_day + datetime.timedelta(days=1)).date()
    cfg.cage_need_clean_look_ahead_hours = 11
    m_dt = mock.MagicMock(spec=datetime.datetime)
    m_dt.now.return_value = mid_day
    monkeypatch.setattr(
        system_maintenance_alarm,
        system_maintenance_alarm.datetime.__name__,
        m_dt,
    )
    maint.set_cage_clean_next_day(tomorrow)
    assert not maint.cage_need_clean_engaged
    m_dt.now.return_value = mid_day + datetime.timedelta(hours=1)
    maint.check_state()
    assert maint.cage_need_clean_engaged
    assert maint.is_engaged
    cfg.cage_need_clean_look_ahead_hours -= 1
    maint.update_config()
    assert not maint.cage_need_clean_engaged
    assert not maint.is_engaged
