import math
from unittest import mock

import psutil
import pytest

from autotrainer.core import PersistenceConfiguration
from autotrainer.core.analysis.free_disk_space_detector import FreeDiskSpaceDetector


@pytest.fixture
def free_disk_space_det():
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
    det.check_state()
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
    det.check_state()
    assert not det.is_engaged
