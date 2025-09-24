
from autotrainer.core.analysis.audio_spectrum_monitor import AudioSpectrumThrashMonitor, \
    AudioSpectrumThrashMonitorConfig


def test_detect_thrashing():

    cfg = AudioSpectrumThrashMonitorConfig()
    monitor = AudioSpectrumThrashMonitor(config=cfg)
    cfg = monitor._config  # in case of it's copied

    assert monitor.is_thrashing_detected is False

    thrash_detected_list = [False]

    def handle_prop_changed(name, new_value, old_value):
        if name == monitor.AUDIO_THRASHING_DETECTED_PROPERTY:
            assert thrash_detected_list[-1] == (not new_value)
            thrash_detected_list.append(new_value)

    monitor.property_changed += handle_prop_changed

    t_now = 0

    idx = 0
    def update_monitor(v, t):
        nonlocal idx
        monitor.update(v, t, idx)
        idx += 1

    low_audio_db = [0.00001 * i for i in range(64)]

    update_monitor(low_audio_db, t_now)

    t_now += 1
    update_monitor(low_audio_db, t_now)

    # value is lower than threshold, so not engaged:
    assert not monitor.is_thrashing_detected
    assert thrash_detected_list == [False]

    # now set value to the desired threshold:
    high_audio_db = [cfg.threshold_db + 0.0001] * 64
    t_now += cfg.time_window + 0.001

    update_monitor(high_audio_db, t_now)
    assert not monitor.is_thrashing_detected  # not yet detected, must wait time_window

    t_now += cfg.time_window + 0.001
    update_monitor(high_audio_db, t_now)

    assert monitor.is_thrashing_detected
    assert thrash_detected_list == [False, True]

    # enqueue enough high_audio_db :
    for _ in range(7):
        t_now += 0.01
        update_monitor(high_audio_db, t_now)

    # obviously still:
    assert monitor.is_thrashing_detected
    assert thrash_detected_list == [False, True]

    # now:
    lower_audio_db = [cfg.threshold_db - 1] * 64  # lower than threshold
    for idx, b in enumerate(cfg.bins_list):
        lower_audio_db[b] = cfg.threshold_db + 1
        if 100 * idx / len(cfg.bins_list) >= cfg.threshold_percent:
            break

    t_now += cfg.time_window

    update_monitor(lower_audio_db, t_now)
    assert monitor.is_thrashing_detected  # still

    very_low_audio = [cfg.threshold_db - 1] * 64  # lower than threshold

    update_monitor(very_low_audio, t_now)

    t_now += cfg.time_window / 2
    update_monitor(very_low_audio, t_now)

    assert not monitor.is_thrashing_detected
    assert thrash_detected_list == [False, True, False]  # False again
