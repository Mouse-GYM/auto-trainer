
import contextlib
import logging

import pytest

from autotrainer.behavior import IntersessionState
from top_fixtures import MockSystemMachine


class TestBatchAnalysis(MockSystemMachine):

    @pytest.fixture(autouse=True)
    def _init_batch_analysis(self, machine):
        algo = self.algo
        algo.intersession_enabled = True
        algo.batch_session_recording_config.enabled = True
        # make test life easier:
        machine._delay_timer_consider_end_session = 0  # TODO: use some config

    @pytest.mark.parametrize("max_batch_size", [2, 5])
    def test_with_max_batch_size(self, machine, max_batch_size, caplog):
        algo = self.algo
        pellet = self.pellet
        algo.batch_session_recording_config.maximum_batch_size = max_batch_size
        self.start_session_in_tunnel()

        batch_start_count = 0
        def batch_starting(batch_len):
            nonlocal batch_start_count
            assert batch_len == max_batch_size
            batch_start_count += 1

        batch_end_count = 0
        def batch_ending(failed_count):
            nonlocal batch_end_count
            assert failed_count == 0
            batch_end_count += 1

        algo.batch_analysis_starting += batch_starting
        algo.batch_analysis_ending += batch_ending

        for idx in range(1, max_batch_size + 1):
            algo.update_mouse_seen(True)
            assert machine.intersession.state == IntersessionState.idle
            with contextlib.ExitStack() as stack:
                caplog.clear()
                stack.enter_context(caplog.at_level(logging.DEBUG))
                if idx >= max_batch_size:
                    for _ in range(max_batch_size):
                        stack.enter_context(self.mock_intersession_analysis())
                pellet.force_load_pellet()
                if idx >= max_batch_size:
                    assert machine.intersession.state == IntersessionState.segmentation
                else:
                    assert machine.intersession.state == IntersessionState.idle
            algo.update_pellet_seen(True)
            while pellet._api_status_token is not None:
                self.mock_pellet_ack()
        assert machine.intersession.state == IntersessionState.idle
        assert batch_start_count == batch_end_count == 1

    def test_with_batch_size_1_do_not_use_batch(self, machine, caplog):
        algo = self.algo
        pellet = self.pellet
        algo.batch_session_recording_config.maximum_batch_size = 1
        self.start_session_in_tunnel()

        batch_started = False
        def batch_starting(batch_len):
            nonlocal batch_started
            batch_started = True

        algo.batch_analysis_starting += batch_starting

        with self.mock_intersession_analysis():
            algo.update_mouse_seen(True)
            with caplog.at_level(logging.DEBUG):
                pellet.force_load_pellet()
            assert machine.intersession.state == IntersessionState.segmentation
            algo.update_pellet_seen(True)
            while pellet._api_status_token is not None:
                self.mock_pellet_ack()
        assert not batch_started
        assert "only 1 session in batch, skipping batch" in caplog.text
        assert machine.intersession.state == IntersessionState.idle
