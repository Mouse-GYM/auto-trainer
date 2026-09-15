import pytest
from autotrainer.api import ApiEventKind

from autotrainer.core import EventManager
from top_fixtures import MockSystemMachine, has_api_event_kind, get_api_event_context


def test_with_it(mock_event_manager, request):
    x = EventManager.default()
    assert isinstance(x, EventManager)
    assert not hasattr(x, "_instance")
    x.post_event_content(ApiEventKind.unknown, data="foobar")
    assert has_api_event_kind(ApiEventKind.unknown)
    assert get_api_event_context(ApiEventKind.unknown) == "foobar"
    mock_event_manager.post_event.reset_mock()
    assert not has_api_event_kind(ApiEventKind.unknown)
    assert get_api_event_context(ApiEventKind.unknown) is None
    mock_system = request.getfixturevalue("mock_system")
    mock_system: MockSystemMachine
    assert mock_system.m_post_event.anything


def test_without_it(request):
    x = EventManager.default()
    request.addfinalizer(lambda: x.close())
    assert isinstance(x, EventManager)
    assert x._instance is x
    x.post_event_content(ApiEventKind.unknown)
    with pytest.raises(RuntimeError, match="mock_event_manager not active"):
        has_api_event_kind(ApiEventKind.unknown)
    with pytest.raises(RuntimeError, match="mock_event_manager not active"):
        get_api_event_context(ApiEventKind.unknown)
    mock_system = request.getfixturevalue("mock_system")
    mock_system: MockSystemMachine
    with pytest.raises(RuntimeError, match="mock_event_manager not active"):
        mock_system.m_post_event.anything
