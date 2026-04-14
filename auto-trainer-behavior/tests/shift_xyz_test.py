import contextlib
import logging
import dataclasses
from unittest import mock

import pytest

from autotrainer.behavior import SystemMachine, SystemState, IntersessionState
from autotrainer.behavior.pellet import PelletState
from autotrainer.core import Offset3DTuple
from autotrainer.core.diamond_triangle_config import DiamondTriangleOffsetConfig
from autotrainer.core.reach_event import ReachEvent, ReachEventMethod
from autotrainer.inference.analysis import IntersessionResponse
from top_fixtures import MockSystemMachine, AlmostEqualFloat


def make_reach_events(tuples):
    return [
        ReachEvent(
            init=init,
            end=end,
            max=max_,
            method=method,
            outcome=outcome,
            delay_since_presented=delay,
        )
        for init, end, max_, method, outcome, delay in tuples
    ]


class TestShiftXYZ(MockSystemMachine):

    @pytest.fixture(autouse=True)
    def _load_diamond_config(self, machine, diamond_triangle_config):
        machine.algorithm.diamond_triangle_config = diamond_triangle_config

    def _init(self, machine: SystemMachine):
        super()._init(machine)
        cfg = self.algo.active_config
        min_reach_fail = 5
        cfg.shift_xyz_handler.buffer.minimum_reach_fail = min_reach_fail
        cfg.batch_session_recording.enabled = True
        cfg.batch_session_recording.maximum_batch_size = 6 * min_reach_fail  # big enough to hold 2+ * minimum_reach_fail
        cfg.pellet_delivery.is_intersession_analysis_enabled = True
        machine._delay_timer_consider_end_session = 0
        assert self.algo.intersession_enabled is True

    def make_session(self, stack: contextlib.ExitStack, reach_events, rh_max_vp_list):
        algo = self.algo
        assert algo.is_in_session
        pellet = self.pellet
        self.mock_pose_response(pellet_seen=True, mouse_seen=True)
        cfg = algo.active_config
        other_events = list(filter(
            lambda r: r.method not in {ReachEventMethod.RIGHT_HAND, ReachEventMethod.LEFT_HAND}, reach_events))
        rsp = IntersessionResponse(
            reach_events=reach_events,
            rh_max_vp_list=rh_max_vp_list,
            other_events=other_events,
        )
        stack.enter_context(self.mock_intersession_analysis(results=rsp))
        self.mock_pose_response(pellet_seen=False)
        self.increment_perf_now(cfg.pellet_delivery.max_pellet_missing_seconds)
        self.mock_pose_response(pellet_seen=False, mouse_seen=True)
        # pellet not seen for missing delay
        #   -> load pellet triggered -> stop-session-recording -> not algo.is_in_session
        assert not algo.is_in_session
        self.increment_perf_now(1)
        self.mock_pose_response(pellet_seen=True, mouse_seen=True)
        self.mock_pellet_ack(until_none=True)
        assert pellet.state == PelletState.monitoring
        assert algo.is_in_session

    def test_with_many_failed_reaches_clear_buffer(self, caplog):
        """Assert that the failed RH max vp buffer is only applied once in a batch of trials,
        if that batch contains more than 2 times the nbr of "failed RH max vp".
        """
        fps = 150  # currently hardcoded in intersession_process
        system = self.system_machine
        algo = self.algo
        cfg = algo.active_config
        pellet_dev = self.pellet_dev
        #
        O = Offset3DTuple  # noqa
        rh_max_vp_lists = (
            [O(0, 1, 2), O(-1, 0.2, -0.5)],
            [O(0, 1, 2)],
            [O(-2.3, -1.5, 1.6), O(0, 1, 2), O(-1, 0.2, -0.5), O(0, 1, 2)],
            [O(0, 1, 2)],
        ) * 2
        assert sum(map(len, rh_max_vp_lists)) > 2 * cfg.shift_xyz_handler.buffer.minimum_reach_fail
        #
        expected_shift = Offset3DTuple(-2.0375, 3.4875, 0)
        self.pellet_dev.last_dcs_set_position = Offset3DTuple(-5, 25, -6)
        self.start_session_in_tunnel()
        assert algo.is_in_session
        caplog.clear()
        caplog.set_level(logging.INFO)
        reach_events = make_reach_events(2 * (
            (0, 60, 65, "right_hand", "missed", 0),
            (65, 75, 80, "right_hand", "stalled", 65 / fps),
            (85, 105, 110, "left_hand", "dropped", 85 / fps),
        ))
        with contextlib.ExitStack() as stack:
            for rh_max_vp_list in rh_max_vp_lists:
                #with caplog.at_level(logging.DEBUG):
                self.make_session(stack, reach_events, rh_max_vp_list)
                self.increment_perf_now(3)
            assert pellet_dev.set_x.call_args_list == []
            assert pellet_dev.set_y.call_args_list == []
            assert pellet_dev.set_z.call_args_list == []
            assert system.state == SystemState.tunnel
            self.exit_tunnel()
        assert system.state == SystemState.cage
        assert system.intersession.state == IntersessionState.idle
        assert f"applying pellet send_position shift: {expected_shift.round(1)}" in caplog.text
        # NB: applied shift are in motor coordinate:
        f_m_d = algo.diamond_triangle_config.flips_motor_diamond
        #
        assert pellet_dev.set_x.call_args_list == [
            mock.call(expected_shift.x * f_m_d.x , absolute=False, sender='processed_shift_xyz')]
        assert pellet_dev.set_y.call_args_list == [
            mock.call(expected_shift.y * f_m_d.y, absolute=False, sender='processed_shift_xyz')]
        assert pellet_dev.set_z.call_args_list == []
        #
        shift_handler_ctx = system.shift_xyz_handler.handler.get_context()
        assert len(shift_handler_ctx['failed_reaches_buffer']) > 0
        # there are still remaining entries at the end,
        # because there was other trial(s) after the one which triggered the last clear of the buffer.

    def test_with_tongue_eaten(self, caplog):
        fps = 150
        reaches_list = (
            make_reach_events(
                (
                    (0, 60, 65, "right_hand", "dropped", 0),
                    (65, 75, 80, "right_hand", "dropped", 65 / fps),
                    (85, 105, 110, "left_hand", "dropped", 85 / fps),
                )
            ),
            make_reach_events(((0, 60, 65, "right_hand", "dropped", 0),)),
            make_reach_events(((0, 60, 65, "tongue", "eaten", 0),)),  # tongue eaten !
            make_reach_events((
                (0, 60, 65, "right_hand", "missed", 0),
                (65, 75, 80, "tongue", "missed", 65 / fps),
                (80, 85, 90, "right_hand", "reached", 80 / fps),
                (95, 105, 110, "right_hand", "eaten", 85 / fps),
            )),
        )
        system = self.system_machine
        algo = self.algo
        cfg = algo.active_config
        pellet_dev = self.pellet_dev
        #
        O = Offset3DTuple  # noqa
        rh_max_vp_lists = (
            [O(0, 1, 2), O(-1, 0.2, -0.5)],
            [O(0, 1, 2)],
            [O(-2.3, -1.5, 1.6), O(0, 1, 2), O(-1, 0.2, -0.5), O(0, 1, 2)],
            [O(0, 1, 2)],
        )
        #
        expected_shift = Offset3DTuple(0, 0.5, 0)
        self.pellet_dev.last_dcs_set_position = Offset3DTuple(-5, 25, -6)
        self.start_session_in_tunnel()
        caplog.clear()
        caplog.set_level(logging.INFO)
        with contextlib.ExitStack() as stack:
            for reach_events, rh_max_vp_list in zip(reaches_list, rh_max_vp_lists):
                # with caplog.at_level(logging.DEBUG):
                self.make_session(stack, reach_events, rh_max_vp_list)
                self.increment_perf_now(3)
            # ensure the shift is only applied after the batch finishes:
            assert pellet_dev.set_x.call_args_list == []
            assert pellet_dev.set_y.call_args_list == []
            assert pellet_dev.set_z.call_args_list == []
            assert system.state == SystemState.tunnel
            assert algo.pellet_shift_y_limit is None
            self.exit_tunnel()  # the batch will be started processing with the exit tunnel
        #
        assert algo.pellet_shift_y_limit == 25.5
        assert system.state == SystemState.cage
        assert system.intersession.state == IntersessionState.idle
        assert (
            f"applying pellet send_position shift: {expected_shift.round(1)}"
            in caplog.text
        )
        # NB: applied shift are in motor coordinate:
        f_m_d = algo.diamond_triangle_config.flips_motor_diamond
        #
        assert pellet_dev.set_x.call_args_list == ([
            mock.call(
                expected_shift.x * f_m_d.x, absolute=False, sender="processed_shift_xyz"
            )
        ] if expected_shift.x != 0 else [])
        assert pellet_dev.set_y.call_args_list == ([
            mock.call(
                expected_shift.y * f_m_d.y, absolute=False, sender="processed_shift_xyz"
            )
        ] if expected_shift.y != 0 else [])
        assert pellet_dev.set_z.call_args_list == ([
            mock.call(
                expected_shift.z * f_m_d.z, absolute=False, sender="processed_shift_xyz"
            )
        ] if expected_shift.z != 0 else [])
        #
        shift_handler_ctx = system.shift_xyz_handler.handler.get_context()
        assert shift_handler_ctx["failed_reaches_buffer"] == [], "with tongue-eaten the failed_reaches_buffer is cleared"
        # there are still remaining entries at the end,
        # because there was other trial(s) after the one which triggered the last clear of the buffer.
