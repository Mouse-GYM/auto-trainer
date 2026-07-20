import math
import pytest

from autotrainer.core import PersistenceConfiguration
from autotrainer.core.analysis.free_disk_space_detector import FreeDiskSpaceDetector


@pytest.fixture
def free_disk_space_det():
    return FreeDiskSpaceDetector()


def test_check_state(free_disk_space_det):
    det = free_disk_space_det
    assert isinstance(det, FreeDiskSpaceDetector)
    assert not det.is_engaged
    det.set_persistence_config(PersistenceConfiguration(output_location="/"))
    det.config.min_limit_mb = math.inf  # noqa
    free_disk_space_det.check_state(force=True)
    assert det.is_engaged
    det.config.min_limit_mb = 0
    free_disk_space_det.check_state(force=True)
    assert not det.is_engaged


def test_with_not_exist_location(free_disk_space_det, caplog):
    det = free_disk_space_det
    assert isinstance(det, FreeDiskSpaceDetector)
    assert not det.is_engaged
    det.set_persistence_config(PersistenceConfiguration(output_location="/must-really-not-exist"))
    det.config.min_limit_mb = math.inf  # noqa
    free_disk_space_det.check_state(force=True)
    assert not det.is_engaged, "Does not engage if location does not exist"
    assert "Cannot check disk usage on" in caplog.text
