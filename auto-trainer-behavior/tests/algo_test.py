import pytest

from autotrainer.behavior import BehaviorAlgorithm


@pytest.fixture
def algo():
    BehaviorAlgorithm._no_handler_thread = True
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
