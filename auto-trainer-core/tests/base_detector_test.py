import time
import threading
from typing import Optional
from unittest import mock

import pytest


from autotrainer.core.analysis.detector import BaseDetector


def test_daemon_can_stop_itself(caplog):

    state_checked = threading.Event()

    class DaemonDetector(BaseDetector):
        use_daemon = True
        def _check_state(self) -> Optional[float]:
            self.stop()
            state_checked.set()

    d = DaemonDetector()
    d.start()
    state_checked.wait(3)
    assert not d.running
    assert "stop() from daemon thread" in caplog.text


def test_lock_acquire_timeout(caplog, monkeypatch):

    class Detector(BaseDetector):
        def _check_state(self) -> Optional[float]:
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
    d.start()
    assert "skipping reentrant check" in caplog.text
