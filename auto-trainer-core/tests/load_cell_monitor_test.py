import time
from threading import Timer
from unittest import mock

import pytest


from autotrainer.core import LoadCellMonitor


@pytest.fixture
def load_cell_monitor():
    instance = LoadCellMonitor()
    yield instance


@pytest.mark.parametrize("threshold_duration", [0.2, 0.5, 0.75])
@pytest.mark.parametrize("weight_threshold,thrashing_var_weight_threshold", [
    (10, 25),
    (15, 30),
    (20, 50),
])
@pytest.mark.parametrize("thrashing_var_min_delay,thrashing_var_max_delay", [
    (0.05, 0.15),
    (0.10, 0.30),
    (0.20, 0.45),
    (0.40, 0.80),
])
def test_detect_load_cell_animal_thrashing(
    load_cell_monitor,
    threshold_duration,
    weight_threshold,
    thrashing_var_min_delay,
    thrashing_var_max_delay,
    thrashing_var_weight_threshold,
    mocker,
):
    assert load_cell_monitor.thrashing_detected is False

    mocker.patch("autotrainer.core.analysis.load_cell_monitor._timer_load_cell_engaged")

    cfg = load_cell_monitor.config
    cfg.threshold_duration = threshold_duration
    cfg.weight_active_threshold = weight_threshold
    cfg.thrashing_var_weight_threshold_min = thrashing_var_weight_threshold
    cfg.thrashing_var_weight_threshold_max = 1.5 * thrashing_var_weight_threshold
    cfg.thrashing_var_min_delay = thrashing_var_min_delay
    cfg.thrashing_var_max_delay = thrashing_var_max_delay

    thrash_detected_list = []

    def handle_thrashing_detected(prop_name, new_value, old_value):
        if prop_name == load_cell_monitor.IS_THRASHING_DETECTED_PROPERTY:
            thrash_detected_list.append(new_value)

    load_cell_monitor.property_changed += handle_thrashing_detected

    t_now = 0

    idx = 0
    def update_monitor(v, t):
        nonlocal idx
        load_cell_monitor.update(v, t, idx)
        idx += 1

    value = 0
    update_monitor(value, t_now)

    t_now += cfg.threshold_duration
    update_monitor(value, t_now)

    # value is lower than threshold, so not engaged:
    assert not load_cell_monitor.is_engaged
    assert not load_cell_monitor.thrashing_detected
    assert thrash_detected_list == []

    patched_timer_call_count = 0
    def patched_timer(delay, func):
        nonlocal patched_timer_call_count
        patched_timer_call_count += 1
        assert delay == cfg.threshold_duration
        m_timer = mock.create_autospec(Timer)
        m_timer.start.side_effect = func
        return m_timer

    # now set value a bit more than engaged threshold:
    value = cfg.weight_active_threshold + 0.0001
    t_now += cfg.min_post_event_hold_duration

    with mock.patch("autotrainer.core.analysis.load_cell_monitor._timer_load_cell_engaged", new=patched_timer):
        for _ in range(3):
            # this for _ in range(..):
            # can be necessary if/when using mean() in monitor update function,
            # to get "current" avg value
            update_monitor(value, t_now)
            t_now += cfg.threshold_duration / 2 + 0.001

    assert patched_timer_call_count == (1 if load_cell_monitor.use_timer else 0)
    assert load_cell_monitor._t_start_was_active is not None
    assert load_cell_monitor.is_engaged
    assert not load_cell_monitor.thrashing_detected

    # check for thrashing:
    t_now += 0.1
    pushed_weight = cfg.weight_active_threshold + cfg.thrashing_var_weight_threshold_min + 0.1
    # not detected atm :
    assert load_cell_monitor.thrashing_detected is False
    assert thrash_detected_list == []

    for outer_loop_idx in range(cfg.thrashing_min_ptp_change_count):
        for inner_loop_idx in range(2):
            # makes 2 loops with high & low values, with delay being a fourth of min delay,
            # this allows to effectively, and normally for any of these values,
            # get the live ptp change count to reach the desired config value,
            # so to trigger the thrashing_detected property/flag.
            t_now += cfg.thrashing_var_min_delay / 4
            update_monitor(cfg.weight_active_threshold, t_now)
            if outer_loop_idx <= 1:
                # NB: this depends on min_ptp_change_count too, and actually on the delays as well
                assert not load_cell_monitor.thrashing_detected
            #
            t_now += cfg.thrashing_var_min_delay / 4
            update_monitor(min(cfg.weight_active_threshold / 2, cfg.thrashing_var_weight_threshold_min / 2), t_now)
            #
            t_now += cfg.thrashing_var_min_delay / 4
            update_monitor(1.5 * pushed_weight, t_now)
            if outer_loop_idx < cfg.thrashing_min_ptp_change_count - 1:
                # NB: this depends on min_ptp_change_count too, and actually on the delays as well
                assert not load_cell_monitor.thrashing_detected
            #
            t_now += cfg.thrashing_var_min_delay / 4
            update_monitor(pushed_weight, t_now)
            if outer_loop_idx == 0:
                # NB: this depends on min_ptp_change_count too, and actually on the delays as well
                assert not load_cell_monitor.thrashing_detected

    # at the end it is detected:
    assert load_cell_monitor.thrashing_detected is True
    assert thrash_detected_list == [True]

    # now, with enough time passed, put back 2 near values :
    t_now += cfg.thrashing_var_max_delay
    update_monitor(cfg.weight_active_threshold + 0.1, t_now)
    #
    t_now += cfg.thrashing_var_min_delay
    update_monitor(cfg.weight_active_threshold + 0.2, t_now)

    assert load_cell_monitor.thrashing_detected is False
    assert thrash_detected_list == [True, False]
    assert load_cell_monitor.is_engaged
