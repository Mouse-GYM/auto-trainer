"""Assert the on-the-wire shape of the trial-scoped API events that gained ``session_id`` /
``trial_id`` in auto-trainer-api v0.9.24, so a future field drift is caught."""
import time
from typing import List, Optional

from autotrainer.api import ApiEventKind, build_event
from autotrainer.core import EventManager, EventManagerPlugin, EventInfo, ProjectInfo

from top_fixtures import MockSystemMachine


class RecordingEventPlugin(EventManagerPlugin):
    """Records every posted event, so a whole session/trial sequence can be asserted on."""

    def __init__(self):
        self.project: Optional[ProjectInfo] = None
        self.enabled = True
        self.events: List[EventInfo] = []

    def set_project(self, project: Optional[ProjectInfo]) -> None:
        self.project = project

    def set_enable(self, enable: bool) -> None:
        self.enabled = enable

    def process_event(self, info: EventInfo, repeat_count: int) -> None:
        self.events.append(info)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass

    def context_for(self, kind: ApiEventKind):
        for info in self.events:
            if info.kind == kind:
                return info.context
        return None


def _drain(manager: EventManager):
    while manager.has_pending():
        time.sleep(0.001)


class TestApiEventPayloads(MockSystemMachine):

    def test_session_start_events_carry_session_and_trial(self, machine):
        manager = EventManager.default()
        recorder = RecordingEventPlugin()
        manager.register_plugin(recorder)

        project = self.algo._project_info  # noqa: SLF001
        assert project.is_valid()
        assert self.algo.start_session(reason="manual") is True
        _drain(manager)

        project_trial_changed = recorder.context_for(ApiEventKind.projectTrialChanged)
        assert project_trial_changed is not None
        assert project_trial_changed["session_id"] == project.session_id
        assert project_trial_changed["trial_id"] == project.trial
        assert project_trial_changed["root"] == project.root

        trial_started = recorder.context_for(ApiEventKind.trialStarted)
        assert trial_started is not None
        assert trial_started["session_id"] == project.session_id
        assert trial_started["trial_id"] == project.trial
        assert "reason" in trial_started

    def test_trial_capture_ended_drops_reason(self, machine):
        manager = EventManager.default()
        recorder = RecordingEventPlugin()
        manager.register_plugin(recorder)

        project = self.algo._project_info  # noqa: SLF001
        assert self.algo.start_session(reason="manual") is True
        assert self.algo.end_capture_session() is True
        _drain(manager)

        capture_ended = recorder.context_for(ApiEventKind.trialCaptureEnded)
        assert capture_ended is not None
        assert set(capture_ended.keys()) == {"session_id", "trial_id"}
        assert capture_ended["session_id"] == project.session_id
        assert "reason" not in capture_ended


def test_project_trial_changed_replaced_project_session_changed():
    # projectSessionChanged (702) was renamed to projectTrialChanged (same value) in v0.9.24.
    assert not hasattr(ApiEventKind, "projectSessionChanged")
    assert hasattr(ApiEventKind, "projectTrialChanged")


def test_batch_analysis_payload_field_names():
    started = build_event(
        ApiEventKind.batchAnalysisStarted, {"session_id": "sess-1", "trial_count": 4})
    assert set(started["context"].keys()) == {"session_id", "trial_count"}

    ended = build_event(
        ApiEventKind.batchAnalysisEnded, {"session_id": "sess-1", "failed_trial_count": 1})
    assert set(ended["context"].keys()) == {"session_id", "failed_trial_count"}
