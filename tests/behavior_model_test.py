

def test_save_config_include_sensor_analysis_monitors_and_detectors(behavior_model):
    save = behavior_model.save_configuration
    analysis = behavior_model.analysis
    #
    cfg = analysis.global_animal_presence_monitor.config
    cfg.presence_missing_delay_hours += 1
    new = cfg.presence_missing_delay_hours
    assert save().global_animal_presence.presence_missing_delay_hours == new
    #
    cfg = analysis.auto_tunnel_sweep_monitor.config
    new = cfg.enabled = not cfg.enabled
    assert save().auto_tunnel_sweep.enabled == new
    #
    thresh = analysis.headbar_pressure_monitor.load_cell_engaged_threshold
    new = analysis.headbar_pressure_monitor.load_cell_engaged_threshold = thresh + 5
    assert save().headbar_pressure.threshold == new
    #
    val = analysis.load_cell_monitor.config.threshold_duration
    new = analysis.load_cell_monitor.config.threshold_duration = val + 3
    assert save().load_cell.threshold_duration == new
    #
    val = analysis.emergency_alarm_monitor.config.use_external_doors_open
    new = analysis.emergency_alarm_monitor.config.use_external_doors_open = not val
    assert save().emergency_alarm.use_external_doors_open == new
    #
    val = analysis.auto_tunnel_sweep_monitor.config.enabled
    new = analysis.auto_tunnel_sweep_monitor.config.enabled = not val
    assert save().auto_tunnel_sweep.enabled == new
    #
    val = analysis.load_cell_tare_monitor.threshold
    new = analysis.load_cell_tare_monitor.threshold = val + 8
    assert save().auto_tare.threshold == new
    #
    val = analysis.audio_thrashing_monitor.config.threshold_percent
    new = analysis.audio_thrashing_monitor.config.threshold_percent = val + 5
    assert save().audio.threshold_percent == new
