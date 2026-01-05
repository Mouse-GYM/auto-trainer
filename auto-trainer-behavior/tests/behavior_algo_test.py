import math

import pytest

from autotrainer.behavior import BehaviorAlgorithm, DiamondTriangleOffsetConfig
from autotrainer.behavior.behavior_algorithm import CoverServoStatus
from autotrainer.core import BehaviorConfiguration, Offset3DTuple


@pytest.fixture
def algo(monkeypatch) -> BehaviorAlgorithm:
    monkeypatch.setattr(BehaviorAlgorithm, "_no_handler_thread", True)
    assert BehaviorAlgorithm._no_handler_thread is True
    algo = BehaviorAlgorithm()
    return algo
    # in case need cleanup


def test_properties(algo):
    algo.auto_clamp_release_tone_freq = 42
    assert algo.auto_clamp_release_tone_freq == 42
    assert algo.cover_servo_status is CoverServoStatus.OK
    assert not algo.cover_servo_status.is_error
    algo.cover_servo_status = CoverServoStatus.COVER_POSITION_ERROR
    assert algo.cover_servo_status.is_error
    assert math.isinf(algo.triangle_last_seen) and algo.triangle_last_seen < 0
    assert algo.diamond_recently_seen is False
    assert algo.triangle_recently_seen is False
    assert algo.pellet_recently_seen is False
    assert algo.presence_missing is False
    algo.presence_missing = True
    assert algo.presence_missing is True
    assert algo.triangle_pellet_offset == Offset3DTuple(math.nan, math.nan, math.nan)
    o3d = algo.triangle_pellet_offset = Offset3DTuple(1, 1, 1)
    assert algo.triangle_pellet_offset == o3d
    t = algo.triangle_pellet_diff_too_far_threshold + 1
    algo.triangle_pellet_diff_too_far_threshold = t
    assert algo.triangle_pellet_diff_too_far_threshold == t


def test_set_put_func_call_mode(algo):

    def record_sync_call_mode(result):
        result.append(getattr(algo._thread_locals, "sync_call_mode"))

    result = []
    prev = getattr(algo._thread_locals, "sync_call_mode", None)
    with algo.set_put_func_call_mode(False):
        algo.put_func_call(record_sync_call_mode, (result,), None)
        assert result[-1] is False
        #
        with algo.set_put_func_call_mode(True):
            algo.put_func_call(record_sync_call_mode, (result,), None)
            assert result[-1] is True
        #
        algo.put_func_call(record_sync_call_mode, (result,), None)
        assert result[-1] is False
    #
    algo.put_func_call(record_sync_call_mode, (result,), None)
    assert prev is result[-1]


@pytest.mark.parametrize("count", [5, 10])
def test_reset_config(algo, count):
    algo.reset_configuration()
    config = BehaviorConfiguration()
    config.head_clamp.auto_clamp_release_load_count = count
    algo.load_configuration(config)
    assert algo.auto_clamp_release_load_count == count
    algo.auto_clamp_release_load_count = 2 * count
    algo.reset_configuration()
    assert algo.auto_clamp_release_load_count == count


def test_start_twice_session_fails(algo):
    assert algo.is_in_session is False
    assert algo.start_session(reason="manual") is True
    assert algo.is_in_session is True
    assert algo.start_session(reason="manual") is False
    assert algo.is_in_session is True


def test_end_session_if_not_running_fails(algo):
    assert algo.is_in_session is False
    assert algo.end_capture_session(reason="manual") is False
    assert algo.is_in_session is False


def test_algo_paused(algo):
    algo.algo_paused = True
    assert algo.can_send_pellet() is False
    assert algo.can_release_pellet() is False
    assert algo.can_cover_pellet() is False
    assert algo.can_load_pellet() is False
    assert algo.start_session() is False
    algo.algo_paused = False
    assert algo.can_send_pellet() is True
    assert algo.can_cover_pellet() is True
    assert algo.can_load_pellet() is True


def test_diamond_triangle_drift(algo):
    algo.diamond_triangle_config = DiamondTriangleOffsetConfig(
        used_position=Offset3DTuple(1, 2, 3),
        measured_offset=Offset3DTuple(3, 30, -8),
    )
    o1 = Offset3DTuple(0.5, 1, -1)
    p1 = Offset3DTuple(8, 6, 5)
    assert algo.get_diamond_triangle_drifts() is None
    algo.handle_diamond_triangle_offset(o1, p1)
    d1 = algo.get_diamond_triangle_drifts()
    assert d1 is not None
    algo.handle_diamond_triangle_offset(o1, p1)
    d1 = algo.get_diamond_triangle_drifts()
    d2 = algo.get_diamond_triangle_drifts()
    assert d1 == d2
    algo.get_diamond_triangle_drifts(reset=True)
    assert algo.get_diamond_triangle_drifts() is None


def test_cover_pellet_offset(algo):
    o1 = Offset3DTuple(1, 2, 3)
    o2 = Offset3DTuple(3, 4, 5)
    algo.handle_cover_pellet_offset(o1)
    algo.handle_cover_pellet_offset(o2)
    # todo: continue...


def test_release_pellet_offset(algo):
    o1 = Offset3DTuple(1, 2, 3)
    o2 = Offset3DTuple(3, 4, 5)
    algo.handle_release_pellet_offset(o1)
    algo.handle_release_pellet_offset(o2)
    # todo: continue...
