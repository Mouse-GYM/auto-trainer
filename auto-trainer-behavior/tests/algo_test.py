import pytest

from autotrainer.behavior import BehaviorAlgorithm
from autotrainer.core import BehaviorConfiguration


@pytest.fixture
def algo(monkeypatch):
    monkeypatch.setattr(BehaviorAlgorithm, "_no_handler_thread", True)
    assert BehaviorAlgorithm._no_handler_thread is True
    algo = BehaviorAlgorithm()
    yield algo
    # in case need cleanup


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
    config = BehaviorConfiguration()
    config.head_clamp.auto_clamp_release_load_count = count
    algo.load_configuration(config)
    assert algo.auto_clamp_release_load_count == count
    algo.auto_clamp_release_load_count = 2 * count
    algo.reset_configuration()
    assert algo.auto_clamp_release_load_count == count
