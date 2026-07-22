"""Assert the on-the-wire shape of the trial-scoped API events that gained ``session_id`` /
``trial_id`` in auto-trainer-api v0.9.24, so a future field drift is caught."""
import pytest
from autotrainer.api import ApiEventKind, build_event

from autotrainer.behavior import SystemMachine

from top_fixtures import MockSystemMachine


class TestApiEventPayloads(MockSystemMachine):

    def _init(self, machine: SystemMachine):
        super()._init(machine)
        self.mock_event_manager()

    def test_trial_start_events_carry_session_and_trial(self, machine):
        get_event_ctx = self.get_event_context
        project = self.algo._project_info  # noqa: SLF001
        assert project.is_valid()
        self.start_trial_in_tunnel()
        assert self.algo.start_trial_capture(reason="manual") is True

        sess_started_ctx = get_event_ctx(ApiEventKind.sessionStarted)
        assert sess_started_ctx.keys() == {"session_id", "is_analysis_deferred"}

        project_trial_changed = get_event_ctx(ApiEventKind.projectTrialChanged)
        assert project_trial_changed is not None
        assert project_trial_changed.keys() == {"session_id", "trial_id", "root"}
        assert project_trial_changed["session_id"] == project.session_id
        assert project_trial_changed["trial_id"] == project.trial
        assert project_trial_changed["root"] == project.root

        trial_started = get_event_ctx(ApiEventKind.trialStarted)
        assert trial_started is not None
        assert trial_started["session_id"] == project.session_id
        assert trial_started["trial_id"] == project.trial
        assert "reason" in trial_started

    def test_trial_capture_ended_drops_reason(self, machine):
        project = self.algo._project_info  # noqa: SLF001
        assert self.algo.start_trial_capture(reason="manual") is True
        assert self.algo.end_capture_trial() is True
        capture_ended = self.get_event_context(ApiEventKind.trialCaptureEnded)
        assert capture_ended is not None
        assert set(capture_ended.keys()) == {"session_id", "trial_id"}
        assert capture_ended["session_id"] == project.session_id
        assert "reason" not in capture_ended


def test_project_trial_changed_replaced_project_session_changed():
    # projectSessionChanged (702) was renamed to projectTrialChanged (same value) in v0.9.24.
    assert not hasattr(ApiEventKind, "projectSessionChanged")
    assert hasattr(ApiEventKind, "projectTrialChanged")
