from typing import Optional

import pytest
from autotrainer.api import ApiEventKind

from autotrainer.core.analysis.detector import BaseDetector
from autotrainer.core.analysis.system_fault_monitor import SystemFaultAlarm
from top_fixtures import has_api_event_kind


@pytest.fixture(autouse=True)
def _use_mock_event_manager(mock_event_manager):
    pass


@pytest.fixture()
def system_fault_alarm(_use_mock_event_manager):
    alarm = SystemFaultAlarm()
    alarm.use_daemon = False  # ensure sync, easier test case
    alarm.start()
    try:
        yield alarm
    finally:
        alarm.stop()


def test_alarm_changed_counts(system_fault_alarm, mock_event_manager):
    # prepare:
    class Detector(BaseDetector):
        def _check_state(self, *, force: bool=False) -> Optional[float]:
            pass
    det1 = Detector()
    det2 = Detector()
    engaged_reasons_changed = []
    def on_prop_changed(name, new_val, old_val):
        if name == system_fault_alarm.ENGAGED_REASONS_CHANGED:
            engaged_reasons_changed.append((name, new_val, old_val))
    system_fault_alarm.property_changed += on_prop_changed
    system_fault_alarm.register_sub_detector("det1", det1)
    system_fault_alarm.register_sub_detector("det2", det2)
    assert det1.running and det2.running
    assert not has_api_event_kind(ApiEventKind.alarmChanged)  # ensure not present before start
    # Now:
    det1.is_engaged = True
    assert det1.is_engaged  # obv
    assert system_fault_alarm.is_engaged  # hopefully
    assert has_api_event_kind(ApiEventKind.alarmChanged), "should see alarmChanged"
    assert len(engaged_reasons_changed) == 1
    mock_event_manager.reset_mock()
    assert not has_api_event_kind(ApiEventKind.alarmChanged)  # ensure well reset
    det2.is_engaged = True
    assert not has_api_event_kind(ApiEventKind.alarmChanged), "alarmChanged should not be reemitted"
    assert system_fault_alarm.engaged_reasons == ["det1", "det2"], "but engaged_reasons should be updated"
    assert len(engaged_reasons_changed) == 2
    engaged_reasons_changed.clear()
    mock_event_manager.reset_mock()
    # Now:
    system_fault_alarm.is_engaged = False  # force disengage
    assert not system_fault_alarm.is_engaged
    assert system_fault_alarm.engaged_reasons == [], "engaged_reasons should be updated"
    assert len(engaged_reasons_changed) == 1
    assert has_api_event_kind(ApiEventKind.alarmChanged)
    engaged_reasons_changed.clear()
    mock_event_manager.reset_mock()
    # Now, execute a new check_state()
    system_fault_alarm.check_state()
    assert system_fault_alarm.is_engaged  # back engaged given det1 + det2 are still engaged.
    assert has_api_event_kind(ApiEventKind.alarmChanged)
    assert len(engaged_reasons_changed) == 1
    assert system_fault_alarm.engaged_reasons == ["det1", "det2"], "still both"
    engaged_reasons_changed.clear()
    mock_event_manager.reset_mock()
    # Now, unset engaged on det1 :
    det1.is_engaged = False
    assert not det1.is_engaged
    assert system_fault_alarm.is_engaged  # still
    assert system_fault_alarm.engaged_reasons == ["det2"]
    assert not has_api_event_kind(ApiEventKind.alarmChanged), "alarmChanged should not be reemitted"
    assert len(engaged_reasons_changed) == 1
    engaged_reasons_changed.clear()
    mock_event_manager.reset_mock()
    # continue:
    det2.is_engaged = False
    assert not system_fault_alarm.is_engaged, "system fault should now be disengaged"
    assert system_fault_alarm.engaged_reasons == []
    assert has_api_event_kind(ApiEventKind.alarmChanged), (
        "alarmChanged should have been reemitted"
    )
    assert len(engaged_reasons_changed) == 1
