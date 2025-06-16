import time
from threading import Timer
from unittest import mock

import pytest


from autotrainer.core import LoadCellMonitor


@pytest.fixture
def load_cell_monitor():
    instance = LoadCellMonitor()
    yield instance


def test_detect_thrashing(load_cell_monitor):
    assert load_cell_monitor.thrashing_detected is False

    thrash_detected_list = []

    def handle_thrashing_detected(detected: bool):
        thrash_detected_list.append(detected)

    load_cell_monitor.is_thrashing_detected += handle_thrashing_detected

    t_now = 0

    idx = 0
    def update_cell(v, t):
        nonlocal idx
        load_cell_monitor.update(v, t, idx)
        idx += 1

    value = 0
    update_cell(value, t_now)

    t_now += 1
    update_cell(value, t_now)

    # value is lower than threshold, so not engaged:
    assert not load_cell_monitor.is_engaged
    assert not load_cell_monitor.thrashing_detected
    assert thrash_detected_list == []

    def patched_timer(delay, func):
        assert delay == load_cell_monitor.threshold_duration
        m_timer = mock.create_autospec(Timer)
        m_timer.start.side_effect = func
        return m_timer

    # now set value a bit more than engaged threshold:
    value = load_cell_monitor.load_cell_engaged_threshold + 0.0001
    t_now += 0.01

    with mock.patch("autotrainer.core.analysis.load_cell_monitor._timer_load_cell_engaged", new=patched_timer):
        #
        update_cell(value, t_now)

    assert load_cell_monitor._was_active
    assert load_cell_monitor.is_engaged
    assert not load_cell_monitor.thrashing_detected

    # now set t_now above thrashing min delay:
    t_now += load_cell_monitor.thrashing_var_minimum_delay + 0.000001
    # and value to weight threshold:
    value = load_cell_monitor.thrashing_var_weight_threshold

    load_cell_monitor.update(value, t_now, 3)
    # still not detected:
    assert load_cell_monitor.thrashing_detected is False
    assert thrash_detected_list == []

    t_now += 0.001
    # now double the value (to get ptp calculated value large enough) :
    load_cell_monitor.update(2 * value, t_now, 4)
    assert load_cell_monitor.thrashing_detected is True
    assert thrash_detected_list == [True]
