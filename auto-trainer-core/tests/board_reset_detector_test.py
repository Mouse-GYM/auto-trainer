import random

import pytest

from autotrainer.core.analysis.boards_hardware_reset_detector import BoardsHardwareResetDetector


@pytest.fixture
def detector():
    det = BoardsHardwareResetDetector()
    det.start()
    try:
        yield det
    finally:
        det.stop()


def test_it_engage_with_is_boot(detector):
    detector.update_uptime(0, 0, is_boot=True)
    assert detector.is_engaged


def test_it_engage_with_smaller_uptime(detector):
    # in case of the is_boot=1 message is missed
    detector.update_uptime(0, 100)
    assert not detector.is_engaged
    detector.update_uptime(0, 99)
    assert detector.is_engaged


def test_it_does_not_engage_with_normal_uptime(detector):
    for tgt in (1, 2, 3):
        detector.update_uptime(tgt, random.randint(1, 100))
    for tgt in (1, 2, 3):
        detector.update_uptime(tgt, random.randint(100, 200))
    for tgt in (1, 2, 3):
        detector.update_uptime(tgt, random.randint(200, 300))
    assert not detector.is_engaged
