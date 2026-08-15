import logging
import threading
from functools import partial
from typing import Optional


from autotrainer.core.analysis.detector import GroupBaseDetector, BaseDetector


class Group(GroupBaseDetector):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.check_done = threading.Event()

        def _check_state(self, *, force: bool = False) -> Optional[float]:
            super()._check_state(force=force)
            self.check_done.set()


class Detector(BaseDetector):
    def _check_state(self) -> Optional[float]:
        pass


def test_does_not_check_checking_sub_detector(caplog):

    group = Group()
    det = Detector()
    group.register_sub_detector("sub", det)

    group.start()
    group.check_done.wait(0.5)
    group.check_done.clear()
    assert det.running, "detector should be started with group"

    def set_engaged(*, force: bool=False):
        det.is_engaged = True

    det._check_state = set_engaged

    caplog.clear()

    assert not det.is_engaged
    assert not group.is_engaged

    with caplog.at_level(logging.DEBUG):
        det.check_state()

    group.check_done.wait(0.5)
    group.check_done.clear()

    assert det.is_engaged  # quite obvious
    assert group.is_engaged, "group is_engaged also set"
    #
    det.is_engaged = False  # do not forget, or no event given no change.
    det.need_explicit_check = True
    with caplog.at_level(logging.DEBUG):
        det.check_state()
    group.check_done.wait(0.5)
    group.check_done.clear()


def test_need_explicit_check(caplog):

    group = Group()
    det1 = Detector()
    det2 = Detector()
    group.register_sub_detector("det1", det1)
    group.register_sub_detector("det2", det2)

    def set_engaged(det, *, force: bool=False):
        det.is_engaged = True

    got_called = False
    def note_got_called(*, force: bool=False):
        nonlocal got_called
        got_called = True

    det2.need_explicit_check = True

    group.start()
    group.check_done.wait(0.5)
    group.check_done.clear()

    det1._check_state = partial(set_engaged, det1)
    det2._check_state = note_got_called

    det1.check_state()
    group.check_done.wait(0.5)
    group.check_done.clear()
    assert group.is_engaged
    assert det1.is_engaged
    assert not det2.is_engaged
    assert got_called, "detector2 should have been explicitly checked"
    # now:
    det1.is_engaged = False
    group.check_done.wait(0.5)
    group.check_done.clear()
    assert not group.is_engaged
    #
    got_called = False
    det1._check_state = note_got_called
    det2._check_state = partial(set_engaged, det2)
    det2.check_state()
    group.check_done.wait(0.5)
    group.check_done.clear()
    assert group.is_engaged
    assert det2.is_engaged
    assert not det1.is_engaged  # obv
    assert not got_called, "detector1 should not have been explicitly checked"
