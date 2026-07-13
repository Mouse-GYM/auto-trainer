"""Assert the on-the-wire shape of the trial-scoped API events that gained ``session_id`` /
``trial_id`` in auto-trainer-api v0.9.24, so a future field drift is caught."""
import time
from typing import List, Optional

from autotrainer.api import ApiEventKind, build_event
from autotrainer.api.event import BatchAnalysisStartedContext

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

    def test_trial_start_events_carry_session_and_trial(self, machine):
        manager = EventManager.default()
        recorder = RecordingEventPlugin()
        manager.register_plugin(recorder)

        project = self.algo._project_info  # noqa: SLF001
        assert project.is_valid()
        self.start_trial_in_tunnel()
        assert self.algo.start_trial_capture(reason="manual") is True
        _drain(manager)

        sess_started_ctx = recorder.context_for(ApiEventKind.sessionStarted)
        assert sess_started_ctx.keys() == {"session_id", "is_analysis_deferred"}

        project_trial_changed = recorder.context_for(ApiEventKind.projectTrialChanged)
        assert project_trial_changed is not None
        assert project_trial_changed.keys() == {"session_id", "trial_id", "root"}
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
        assert self.algo.start_trial_capture(reason="manual") is True
        assert self.algo.end_capture_trial() is True
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
