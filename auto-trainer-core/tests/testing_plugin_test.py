import pytest
from autotrainer.api import ApiEventKind

from autotrainer.core import EventManager
from autotrainer.core.testing import get_api_event_context, get_mock_event_manager, has_api_event_kind


def test_mock_event_manager_records_api_events(mock_event_manager):
    manager = EventManager.default()
    assert manager is mock_event_manager
    manager.post_event_content(ApiEventKind.unknown, data="foobar")
    assert has_api_event_kind(ApiEventKind.unknown)
    assert get_api_event_context(ApiEventKind.unknown) == "foobar"
    assert get_mock_event_manager() is mock_event_manager


def test_helpers_need_an_active_mock_event_manager():
    with pytest.raises(RuntimeError, match="mock_event_manager not active"):
        has_api_event_kind(ApiEventKind.unknown)
    with pytest.raises(RuntimeError, match="mock_event_manager not active"):
        get_api_event_context(ApiEventKind.unknown)
    with pytest.raises(RuntimeError, match="mock_event_manager not active"):
        get_mock_event_manager()
