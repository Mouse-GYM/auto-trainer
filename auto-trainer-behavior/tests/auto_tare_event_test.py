import logging
import uuid

import pytest

from autotrainer.api import ApiEventKind
from autotrainer.core.message.message_handler import CommandResult

from top_fixtures import MockSystemMachine


@pytest.fixture(autouse=True)
def _use_mock_event_manager(mock_event_manager):
    pass


def _auto_tare_event_count(mock_system: MockSystemMachine) -> int:
    return sum(
        1 for call in mock_system.m_post_event.call_args_list if call.args[0].kind == ApiEventKind.headfixAutoTare
    )


def _request_auto_tare(mock_system: MockSystemMachine, token):
    mock_system.tunnel_dev.tare_load_cell.return_value = token
    mock_system.system_machine._on_load_cell_tare_requested()  # noqa


def _ack(mock_system: MockSystemMachine, token, result: CommandResult):
    mock_system.msg_handler.ack_received(token, result)


def _tracked_tokens(mock_system: MockSystemMachine):
    return mock_system.system_machine._auto_tare_tokens  # noqa


def test_event_waits_for_successful_ack(mock_system):
    token = uuid.uuid4()
    _request_auto_tare(mock_system, token)
    assert _auto_tare_event_count(mock_system) == 0

    _ack(mock_system, token, CommandResult(succeeded=True))
    assert _auto_tare_event_count(mock_system) == 1

    _ack(mock_system, token, CommandResult(succeeded=True))
    assert _auto_tare_event_count(mock_system) == 1


@pytest.mark.parametrize("result", [
    CommandResult(succeeded=False, error="nack"),
    CommandResult(succeeded=True, skipped=True),
    CommandResult(succeeded=False, error="nack", skipped=True),
])
def test_no_event_for_failed_or_skipped_ack(mock_system, result):
    token = uuid.uuid4()
    _request_auto_tare(mock_system, token)
    _ack(mock_system, token, result)
    assert _auto_tare_event_count(mock_system) == 0

    _ack(mock_system, token, CommandResult(succeeded=True))
    assert _auto_tare_event_count(mock_system) == 0


def test_unrelated_ack_is_ignored(mock_system):
    token = uuid.uuid4()
    _request_auto_tare(mock_system, token)
    _ack(mock_system, uuid.uuid4(), CommandResult(succeeded=True))
    assert _auto_tare_event_count(mock_system) == 0
    assert _tracked_tokens(mock_system) == [token]

    _ack(mock_system, token, CommandResult(succeeded=True))
    assert _auto_tare_event_count(mock_system) == 1


def test_each_successful_auto_tare_posts_one_event(mock_system):
    first, second = uuid.uuid4(), uuid.uuid4()
    _request_auto_tare(mock_system, first)
    _request_auto_tare(mock_system, second)
    _ack(mock_system, first, CommandResult(succeeded=True))
    _ack(mock_system, second, CommandResult(succeeded=True))
    assert _auto_tare_event_count(mock_system) == 2
    assert _tracked_tokens(mock_system) == []


def test_request_without_token_tracks_nothing(mock_system):
    _request_auto_tare(mock_system, None)
    assert _tracked_tokens(mock_system) == []


def test_delayed_success_still_posts_event(mock_system):
    first, second = uuid.uuid4(), uuid.uuid4()
    _request_auto_tare(mock_system, first)
    mock_system.increment_perf_now(600)
    _request_auto_tare(mock_system, second)

    _ack(mock_system, first, CommandResult(succeeded=True))
    assert _auto_tare_event_count(mock_system) == 1
    assert _tracked_tokens(mock_system) == [second]

    _ack(mock_system, second, CommandResult(succeeded=True))
    assert _auto_tare_event_count(mock_system) == 2
    assert _tracked_tokens(mock_system) == []


def test_ack_drops_earlier_unanswered_tokens(mock_system, caplog):
    first, second = uuid.uuid4(), uuid.uuid4()
    _request_auto_tare(mock_system, first)
    _request_auto_tare(mock_system, second)
    with caplog.at_level(logging.WARNING):
        _ack(mock_system, second, CommandResult(succeeded=True))
    assert _auto_tare_event_count(mock_system) == 1
    assert _tracked_tokens(mock_system) == []
    assert "were never acknowledged" in caplog.text

    _ack(mock_system, first, CommandResult(succeeded=True))
    assert _auto_tare_event_count(mock_system) == 1


def test_trial_capture_still_blocks_unforced_tare(mock_system):
    mock_system.algo.update_pellet_seen(True)
    mock_system.start_trial_in_tunnel(set_recording_status=True)
    assert mock_system.algo.is_in_trial_capture

    tare_load_cell = mock_system.tunnel_dev.tare_load_cell
    tare_load_cell.reset_mock()
    mock_system.system_machine._on_load_cell_tare_requested()  # noqa
    tare_load_cell.assert_not_called()

    mock_system.system_machine._on_load_cell_tare_requested(force=True)  # noqa
    tare_load_cell.assert_called_once()
