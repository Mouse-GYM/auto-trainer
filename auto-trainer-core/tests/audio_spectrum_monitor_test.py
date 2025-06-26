
from autotrainer.core.analysis.audio_spectrum_monitor import AudioSpectrumThrashMonitor, \
    AudioSpectrumThrashMonitorConfig


def test_detect_thrashing():

    cfg = AudioSpectrumThrashMonitorConfig()
    monitor = AudioSpectrumThrashMonitor(config=cfg)

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

    audio_db_values = [0] * 64

    update_monitor(audio_db_values, t_now)

    t_now += 1
    update_monitor(audio_db_values, t_now)

    # value is lower than threshold, so not engaged:
    assert not monitor.is_thrashing_detected
    assert thrash_detected_list == [False]

    # now set value to the desired threshold:
    audio_db_values = [cfg.threshold_db] * 64
    t_now += 0.01

    update_monitor(audio_db_values, t_now)
    assert not monitor.is_thrashing_detected  # not yet detected, must wait time_window

    t_now += cfg.time_window + 0.001
    update_monitor(audio_db_values, t_now)

    assert monitor.is_thrashing_detected
    assert thrash_detected_list == [False, True]

    audio_db_values = [cfg.threshold_db - 1] * 64  # lower than threshold

    t_now += 0.1
    update_monitor(audio_db_values, t_now)
    assert monitor.is_thrashing_detected

    t_now += 0.1
    update_monitor(audio_db_values, t_now)
    assert monitor.is_thrashing_detected
    assert thrash_detected_list == [False, True]  # still too

    t_now += 0.1
    update_monitor(audio_db_values, t_now)
    # NB: 3 times to have more values than the previous ones still within the time window
    assert not monitor.is_thrashing_detected
    assert thrash_detected_list == [False, True, False]  # False again
