import math
import pytest

from autotrainer.core.analysis.free_disk_space_detector import FreeDiskSpaceDetector


@pytest.fixture
def free_disk_space_det():
    return FreeDiskSpaceDetector()


def test_check_state(free_disk_space_det):
    det = free_disk_space_det
    assert not det.is_engaged
    det.config.min_limit_mb = math.inf  # noqa
    free_disk_space_det.check_state(force=True)
    assert det.is_engaged
    det.config.min_limit_mb = 0
    free_disk_space_det.check_state(force=True)
    assert not det.is_engaged
