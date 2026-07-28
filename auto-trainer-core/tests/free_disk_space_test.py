import logging
import math
from unittest import mock

import psutil
import pytest

from autotrainer.core import PersistenceConfiguration
from autotrainer.core.analysis.free_disk_space_detector import FreeDiskSpaceDetector
from top_fixtures import increase_simulate_perf_now


@pytest.fixture
def free_disk_space_det(mock_get_perf_now):
    det = FreeDiskSpaceDetector()
    # runs everything in foreground:
    det.use_daemon = False
    det.default_timer_delay = None
    #
    det.start()
    try:
        yield det
    finally:
        det.stop()  # to be clean.


def test_check_state_with_set_persistence_config(free_disk_space_det):
    det = free_disk_space_det
    assert isinstance(det, FreeDiskSpaceDetector)
    assert not det.is_engaged
    det.config.min_limit_mb = math.inf  # noqa
    det.set_persistence_config(PersistenceConfiguration(output_location="/"))
    assert det.is_engaged, "should have engaged from set_persistence_config"
    # now:
    det.config.min_limit_mb = 0
    det.check_state(force=True)
    assert not det.is_engaged


def test_with_not_exist_location(free_disk_space_det, caplog):
    det = free_disk_space_det
    assert isinstance(det, FreeDiskSpaceDetector)
    assert not det.is_engaged
    det.config.min_limit_mb = 0
    det.set_persistence_config(PersistenceConfiguration(output_location="/must-really-not-exist"))
    assert det.is_engaged, "Does engage if location does not exist"
    assert "Cannot check disk usage on" in caplog.text
    det.set_persistence_config(PersistenceConfiguration(output_location="/"))
    assert not det.is_engaged


def test_with_permission_error(
    free_disk_space_det,
    caplog,
    monkeypatch,
):
    det = free_disk_space_det
    orig_usage = psutil.disk_usage
    m = mock.create_autospec(psutil.disk_usage)
    monkeypatch.setattr(psutil, "disk_usage", m)
    m.side_effect = PermissionError("this-is-denied")
    det.set_persistence_config(PersistenceConfiguration(output_location="/"))
    assert det.is_engaged, "Does engage if get permission error"
    assert "Cannot check disk usage on" in caplog.text
    assert "this-is-denied" in caplog.text
    m.side_effect = orig_usage
    det.config.min_limit_mb = -1
    det.check_state(force=True)
    assert not det.is_engaged


@pytest.mark.parametrize("delay", [-1, 0, 15, 30])
def test_recheck_min_delay(free_disk_space_det, delay, caplog):
    det = free_disk_space_det
    cfg = det.config
    cfg.recheck_min_delay = delay
    det.set_persistence_config(PersistenceConfiguration(output_location="/"))
    det.restart()  # to get first one done
    cfg.min_limit_mb = math.inf  # ensure it will trigger is_engaged on next **real** check
    skip_msg = "skipping check due to recheck_min_delay"
    with caplog.at_level(logging.DEBUG):
        det.check_state()
    if delay > 0:
        assert not det.is_engaged
        assert skip_msg in caplog.text
    else:
        assert det.is_engaged
        assert skip_msg not in caplog.text
    caplog.clear()
    #
    det.config = det.config  # now this should trigger a check_state(force=True)
    assert det.is_engaged
    #
    cfg.min_limit_mb = -1
    with caplog.at_level(logging.DEBUG):
        det.check_state()
    if delay <= 0:
        assert not det.is_engaged
        assert skip_msg not in caplog.text
    else:
        assert det.is_engaged
        assert skip_msg in caplog.text
        half = delay / 2
        increase_simulate_perf_now(half)
        det.check_state()
        assert det.is_engaged
        #
        increase_simulate_perf_now(half + .1)
        det.check_state()
        assert not det.is_engaged
