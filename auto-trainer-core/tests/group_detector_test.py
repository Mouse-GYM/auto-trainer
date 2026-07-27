import logging
from typing import Optional

from autotrainer.core.analysis.detector import GroupBaseDetector, BaseDetector


def test_does_not_check_checking_sub_detector(caplog):

    class Group(GroupBaseDetector):
        pass

    class Detector(BaseDetector):
        def _check_state(self) -> Optional[float]:
            pass

    group = Group()
    det = Detector()
    group.register_sub_detector("sub", det)

    group.start()
    assert det.running, "detector should be started with group"

    def set_engaged(*, force: bool=False):
        det.is_engaged = True

    det._check_state = set_engaged

    caplog.clear()

    assert not det.is_engaged
    assert not group.is_engaged

    with caplog.at_level(logging.DEBUG):
        det.check_state()
    assert "prevented possible reentrant/deadlock check_state to sub-detector" in caplog.text
    assert det.is_engaged  # quite obvious
    assert group.is_engaged, "group is_engaged also set"
