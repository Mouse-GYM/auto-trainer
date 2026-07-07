import time
import datetime as dt

import pytest

from autotrainer.api import ApiEventKind, ApiDetectorKind, ApiDetectorStatus, build_event
from autotrainer.core import EventManager, ProjectInfo, EventInfo
from autotrainer.core.event.file_event_plugin import FileEventPlugin
from autotrainer.core.event.logger_event_plugin import LoggerEventPlugin

from mocks import MockEventPlugin


@pytest.fixture
def default_manager():
    yield EventManager.default()
    # Required to close the process_events thread and exit cleanly.
    EventManager.default().close()


@pytest.fixture
def event_manager():
    manager = EventManager("EventManagerInstance")
    yield manager
    manager.close()


@pytest.fixture
def mock_plugin():
    return MockEventPlugin()


def test_default_instance(default_manager):
    # Test the default instance
    assert default_manager is not None, "Default instance should not be None"
    assert isinstance(default_manager, EventManager), "Default instance should be of type EventManager"

    # Test that the default instance is a singleton
    another_event_manager = EventManager.default()
    assert default_manager is another_event_manager, "Default instance should be a singleton"

    plugins = default_manager.plugins
    assert plugins is not None, "Default instance should not be None"
    assert len(plugins) == 2, "Default instance should have 2 plugins"

    assert isinstance(plugins[0], LoggerEventPlugin), "Default plugins should include the logger event plugin"
    assert isinstance(plugins[1], FileEventPlugin), "Default plugins should include the file event plugin"

    default_manager.unregister_plugin(plugins[0])
    updated_plugins = default_manager.plugins
    assert len(updated_plugins) == 1, "Plugin was not removed"
    assert len(plugins) == 2, "List returned from plugins property should have been a copy"
    assert isinstance(default_manager.plugins[0], FileEventPlugin), "Remaining plugin should be a file event plugin"


def test_plugin_interface(event_manager, mock_plugin):
    event_manager.project = ProjectInfo()

    assert mock_plugin.project is None

    event_manager.register_plugin(mock_plugin)

    assert mock_plugin.project == event_manager.project

    next_event = EventInfo(kind=1, when=dt.datetime.now(), index=0)
    event_manager.post_event(next_event)

    # So long as this method provides an accurate response (see docstring for this method), use it instead of some
    # arbitrary sleep() duration to allow the event to be processed.
    while event_manager.has_pending():
        time.sleep(0.001)

    assert mock_plugin.last_event == next_event
    assert mock_plugin.event_count == 1

    event_manager.flush()

    assert event_manager.is_valid is True
    assert mock_plugin.enabled is True
    assert mock_plugin.flushed is True
    #
    event_manager.close()
    #
    assert event_manager.is_valid is False
    assert mock_plugin.enabled is False
    assert mock_plugin.closed is True


def test_post_none_event_refused(event_manager):
    with pytest.raises(RuntimeError, match=r"post_event\(None\) refused"):
        event_manager.post_event(None)  # noqa


def _wait_processed(event_manager):
    while event_manager.has_pending():
        time.sleep(0.001)


def test_post_api_event_restamps_and_posts_context(event_manager, mock_plugin):
    event_manager.register_plugin(mock_plugin)

    built = build_event(
        ApiEventKind.trialStarted, {"session_id": "sess-1", "trial_id": 3, "reason": "NA"})

    event_manager.post_api_event(built)
    _wait_processed(event_manager)

    posted = mock_plugin.last_event
    assert posted.kind == ApiEventKind.trialStarted
    assert posted.context == {"session_id": "sess-1", "trial_id": 3, "reason": "NA"}
    # when/index are re-stamped by post_event_content, not reused from the built dict.
    assert posted.when is not built["when"]
    assert posted.index != built["index"]


def test_post_api_event_normalizes_dataclass_context(event_manager, mock_plugin):
    event_manager.register_plugin(mock_plugin)

    status = ApiDetectorStatus(
        detector_id=ApiDetectorKind.lowFreeDiskSpace, is_active=True, is_enabled=True)
    event_manager.post_api_event(build_event(ApiEventKind.detectorChanged, status))
    _wait_processed(event_manager)

    posted = mock_plugin.last_event
    assert posted.kind == ApiEventKind.detectorChanged
    # build_event asdict()s a dataclass context, so plugins see a plain dict.
    assert posted.context == {
        "detector_id": ApiDetectorKind.lowFreeDiskSpace,
        "is_active": True,
        "is_enabled": True,
    }
