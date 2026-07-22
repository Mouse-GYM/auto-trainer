
import contextlib
import logging

import pytest
from unittest import mock

from autotrainer.behavior import IntertrialState, SystemState, SystemMachine
from autotrainer.behavior.pellet import PelletState
from top_fixtures import MockSystemMachine, FifoExitStack


class TestBatchAnalysis(MockSystemMachine):

    batch_start_count = 0
    batch_len_processed = None

    def batch_starting(self, batch_len):
        self.batch_start_count += 1
        self.batch_len_processed = batch_len

    batch_end_count = 0
    batch_failed_count = None

    def batch_ending(self, failed_count):
        self.batch_failed_count = failed_count
        self.batch_end_count += 1

    @pytest.fixture(autouse=True)
    def _init_batch_analysis(self, machine):
        algo = self.algo
        algo.intertrial_enabled = True
        algo.batch_trial_recording_config.enabled = True
        # make test life easier:
        machine._delay_timer_consider_end_trial = 0  # TODO: use some config
        algo.batch_analysis_starting += self.batch_starting
        algo.batch_analysis_ending += self.batch_ending

    @pytest.mark.parametrize("max_batch_size", [2, 5])
    def test_with_max_batch_size(self, machine, max_batch_size, caplog):
        algo = self.algo
        pellet = self.pellet
        algo.batch_trial_recording_config.maximum_batch_size = max_batch_size
        self.mock_pose_response(pellet_seen=True)
        self.start_trial_in_tunnel(set_recording_status=True)

        for idx in range(1, max_batch_size + 1):
            algo.update_mouse_seen(True)
            assert machine.intertrial.state == IntertrialState.idle
            with FifoExitStack() as stack:
                caplog.clear()
                stack.enter_context(caplog.at_level(logging.DEBUG))
                if idx >= max_batch_size:
                    for _ in range(max_batch_size):
                        self.make_analysis(stack)
                pellet.load_pellet(force=True)
                if idx >= max_batch_size:
                    assert machine.state == SystemState.intertrial
                    assert machine.intertrial.state == IntertrialState.segmentation
                else:
                    assert machine.intertrial.state == IntertrialState.idle
            algo.update_pellet_seen(True)
            self.mock_pellet_ack(until_none=True)
        assert machine.state == SystemState.tunnel
        assert machine.intertrial.state == IntertrialState.idle
        assert self.batch_start_count == self.batch_end_count == 1
        assert self.batch_len_processed == max_batch_size
        assert self.batch_failed_count == 0

    def test_with_batch_size_1_also_use_batch(self, machine, caplog):
        algo = self.algo
        pellet = self.pellet
        algo.batch_trial_recording_config.maximum_batch_size = 1
        self.mock_pose_response(pellet_seen=True)
        self.start_trial_in_tunnel(set_recording_status=True)
        with self.mock_analysis():
            algo.update_mouse_seen(True)
            with caplog.at_level(logging.DEBUG):
                pellet.load_pellet(force=True)
            assert machine.state == SystemState.intertrial
            assert machine.intertrial.state == IntertrialState.segmentation
            algo.update_pellet_seen(True)
            self.mock_pellet_ack(until_none=True)

        assert machine.state == SystemState.tunnel
        assert self.batch_start_count == 1
        assert self.batch_len_processed == 1
        assert machine.intertrial.state == IntertrialState.idle

    @pytest.mark.parametrize("last_trial_with_mouse", [False, True])
    @pytest.mark.parametrize("trials_count", [1, 3])
    def test_with_exit_tunnel(self, machine, caplog, last_trial_with_mouse, trials_count):
        algo = self.algo
        pellet = self.pellet

        self.mock_pose_response(pellet_seen=True)
        self.start_trial_in_tunnel(set_recording_status=True)

        for idx in range(trials_count):
            assert algo.is_in_trial_capture
            self.mock_pose_response(pellet_seen=True, mouse_seen=True)
            pellet.load_pellet(force=True)
            assert not algo.is_in_trial_capture
            self.mock_pose_response(pellet_seen=True, mouse_seen=True)
            self.mock_pellet_ack(until_none=True)

        if last_trial_with_mouse:
            algo.update_mouse_seen(True)

        assert machine.state == SystemState.tunnel
        assert machine.intertrial.state == IntertrialState.idle

        expected_batch_len = trials_count + (1 if last_trial_with_mouse else 0)

        with FifoExitStack() as stack:
            for _ in range(expected_batch_len):
                self.make_analysis(stack)
            stack.enter_context(caplog.at_level(logging.DEBUG))
            self.make_load_cell_inactive()
            assert machine.state == SystemState.intertrial
            assert machine.intertrial.state == IntertrialState.segmentation

        assert machine.state == SystemState.cage
        assert machine.intertrial.state == IntertrialState.idle
        assert self.batch_len_processed == expected_batch_len
        assert self.batch_start_count == self.batch_end_count == 1

    def test_exit_tunnel_while_loading(self, machine, caplog):
        pellet = self.pellet
        self.mock_pose_response(pellet_seen=True)
        self.start_trial_in_tunnel(set_recording_status=True)
        self.mock_pose_response(pellet_seen=True, mouse_seen=True)
        pellet.load_pellet(force=True)
        # don't ack load-pellet, but make exit tunnel now
        with self.mock_analysis():
            with caplog.at_level(logging.DEBUG):
                self.exit_tunnel()
        assert self.batch_start_count == 1
        assert self.batch_end_count == 1
        assert self.batch_len_processed == 1
        assert "enter_intertrial: reason=exit-tunnel-with-trials-batch-list" in caplog.text

    def test_exit_tunnel_while_batch_analysis_in_progress(self, machine, caplog):
        algo = self.algo
        pellet = self.pellet
        n_trials = 2
        algo.active_config.batch_trial_recording.maximum_batch_size = n_trials
        #
        self.start_trial_in_tunnel(set_recording_status=True)
        self.mock_pose_response(pellet_seen=True, mouse_seen=True)
        with FifoExitStack() as stack:
            for _  in range(n_trials):
                self.mock_pose_response(pellet_seen=True, mouse_seen=True)
                self.mock_pellet_ack(until_none=True)
                assert pellet.state == PelletState.monitoring
                self.make_analysis(stack)
                # trigger load and end-capture-session:
                self.mock_pellet_missing(mouse_seen=True)
                if algo.system_state == SystemState.intertrial:
                    assert pellet.state == PelletState.retract
                else:
                    assert pellet.state == PelletState.loading
            assert machine.state == SystemState.intertrial
            #
            with caplog.at_level(logging.DEBUG):
                self.exit_tunnel()  # expected log happen here
            expected_txt = (
                f"exit_tunnel but intertrial state={IntertrialState.segmentation!s}, doing nothing."
                f" n_batch_trials={n_trials}"
            )
            assert expected_txt in caplog.text
            assert machine.state == SystemState.intertrial  # still
