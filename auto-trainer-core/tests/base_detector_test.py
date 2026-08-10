import logging
import time
import threading
from typing import Optional
from unittest import mock

import pytest


from autotrainer.core.analysis.detector import BaseDetector


class DaemonDetector(BaseDetector):
    use_daemon = True

    def __init__(self):
        super().__init__()
        self.state_checked = threading.Event()

    def _check_state(self, *, force=False) -> Optional[float]:
        self.state_checked.set()

    orig_check = _check_state


class TestDaemonDetector:

    @pytest.fixture()
    def detector(self):
        det = DaemonDetector()
        try:
            yield det
        finally:
            det.stop()

    def test_it_can_stop_itself(self, caplog, detector):

        def check_stop(*args, **kwargs):
            detector.stop()
            detector.orig_check()

        detector._check_state = check_stop
        detector.start()
        detector.state_checked.wait(3)
        assert not detector.running
        assert "stop() from daemon thread" in caplog.text

    def test_with_force(self, caplog, detector):
        force_obtained = None
        set_engaged = None
        def check_force(*args, force: bool=False, **kwargs):
            nonlocal force_obtained, set_engaged
            force_obtained = force
            if set_engaged is not None:
                detector.is_engaged = set_engaged
                set_engaged = None
            detector.orig_check()

        detector._check_state = check_force
        detector.start()
        assert detector.state_checked.wait(5)
        detector.state_checked.clear()
        assert force_obtained is True, "a first forced check state is done at daemon start"
        force_obtained = None

        detector.check_state(force=True)
        assert detector.state_checked.wait(5)
        detector.state_checked.clear()
        assert force_obtained is True

        force_obtained = None
        detector.check_state()
        assert detector.state_checked.wait(5)
        detector.state_checked.clear()
        assert force_obtained is False

        force_obtained = None
        detector.stop()
        detector.check_state()
        assert not detector.state_checked.wait(0.25)
        assert force_obtained is None
        #
        set_engaged = True
        detector.check_state(force=True)
        assert detector.state_checked.wait(5)
        detector.state_checked.clear()
        assert force_obtained is True
        assert detector.is_engaged
        #
        set_engaged = False
        detector.check_state()
        assert not detector.state_checked.wait(0.25)
        assert detector.is_engaged
        detector.check_state(force=True)
        assert detector.state_checked.wait(5)
        assert not detector.is_engaged


def test_lock_acquire_timeout(caplog, monkeypatch):

    class Detector(BaseDetector):
        pass

    det = Detector()
    det.start()
    m = mock.MagicMock(spec=det._lock)
    m.acquire.return_value = False
    monkeypatch.setattr(det, "_lock", m)
    det.check_state()
    assert "could not acquire lock \"fast\" enough, skipping check" in caplog.text


def test_reentrant_check_state_does_not_loop(caplog):

    class Detector(BaseDetector):
        def _check_state(self) -> Optional[float]:
            self.check_state()

    d = Detector()
    caplog.set_level(logging.DEBUG)
    d.start()
    assert "skipping reentrant check" in caplog.text
