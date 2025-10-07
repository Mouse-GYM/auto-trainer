import time

from autotrainer.core import ObservableObject, LoadCellMonitor
from autotrainer.core.analysis.audio_spectrum_monitor import AudioSpectrumThrashMonitor
from autotrainer.core.configuration.alarm_configuration import EmergencyAlarmConfiguration
from autotrainer.behavior import BehaviorAlgorithm


class EmergencyAlarmMonitor(ObservableObject):

    def __init__(self, config: EmergencyAlarmConfiguration, load_cell_monitor: LoadCellMonitor, audio_monitor: AudioSpectrumThrashMonitor):
        super().__init__()
        self._config = config
        self._load_cell_monitor = load_cell_monitor
        self._audio_monitor = audio_monitor
        self._load_cell_thrash_values = []
        self._load_cell_engaged_values = []
        self._audio_thrash_values = []
        self._is_engaged = False
        load_cell_monitor.property_changed += self._load_cell_monitor_prop_changed
        audio_monitor.property_changed += self._audio_prop_changed

    @property
    def is_engaged(self):
        return self._is_engaged

    @is_engaged.setter
    def is_engaged(self, value):
        prev, self._is_engaged = self._is_engaged, value
        self._on_property_changed("is_engaged", value, prev)

    @BehaviorAlgorithm.relay_func(wait=False)
    def _update_state(self):
        cfg = self._config
        perf_now = time.perf_counter()
        #
        for values in (self._load_cell_engaged_values, self._load_cell_thrash_values, self._audio_thrash_values):
            idx = len(values) - 1
            t_perf = values[idx][0]
            if perf_now - t_perf > cfg.aggregate_delay:
                del values[:idx + 1]
        #
        if self._load_cell_monitor.is_engaged:
            # unless otherwise required.
            self.is_engaged = False
            return
        #
        count_load_cell_thrash_triggers = 0
        tot_load_cell_thrash_engaged = 0
        v = None
        perf_c_start = perf_now - cfg.aggregate_delay

        for idx, v in enumerate(self._load_cell_thrash_values):
            if v[1]:
                count_load_cell_thrash_triggers += 1
            else:
                tot_load_cell_thrash_engaged += (v[0] - perf_c_start) if idx == 0 else v[2]
        if v is not None:
            if v[1]:
                tot_load_cell_thrash_engaged += perf_now - v[0]
        elif self._load_cell_monitor.thrashing_detected:
            tot_load_cell_thrash_engaged += cfg.aggregate_delay
        #
        count_audio_thrash_triggers = 0
        tot_audio_thrash_engaged = 0
        v = None
        for idx, v in enumerate(self._audio_thrash_values):
            if v[1]:
                count_audio_thrash_triggers += 1
            else:
                tot_audio_thrash_engaged += (v[0] - perf_c_start) if idx == 0 else v[2]
        if v is not None:
            if v[1]:
                tot_audio_thrash_engaged += perf_now - v[0]
        elif self._audio_monitor.is_thrashing_detected:
            tot_audio_thrash_engaged += cfg.aggregate_delay
        #
        pc_load_cell_thrash = 100 * tot_load_cell_thrash_engaged / cfg.aggregate_delay
        pc_audio_thrash = 100 * tot_audio_thrash_engaged / cfg.aggregate_delay
        is_emergency = (
            (
                pc_load_cell_thrash >= cfg.load_cell_thrash_percent_on
                or count_load_cell_thrash_triggers >= cfg.load_cell_thrash_count
            ) and (
                pc_audio_thrash >= cfg.spectrum_thrash_percent_on
                or count_audio_thrash_triggers >= cfg.spectrum_thrash_count
            )
        )
        self.is_engaged = is_emergency

    @BehaviorAlgorithm.relay_func(wait=False)
    def _load_cell_monitor_prop_changed(self, name, value, _):
        perf_now = time.perf_counter()
        load_cell = self._load_cell_monitor
        if name == LoadCellMonitor.IS_THRASHING_DETECTED_PROPERTY:
            self._load_cell_thrash_values.append((perf_now, value,
                                                  load_cell.thrashing_disengaged_age if value
                                                  else load_cell.thrashing_engaged_age))
            self._update_state()
        elif name == LoadCellMonitor.IS_ENGAGED_PROPERTY:
            self._load_cell_engaged_values.append((perf_now, value,
                                                   load_cell.disengaged_age if value
                                                   else load_cell.engaged_age
                                                   ))
            self._update_state()

    @BehaviorAlgorithm.relay_func(wait=False)
    def _audio_prop_changed(self, name, value, _):
        if name == AudioSpectrumThrashMonitor.AUDIO_THRASHING_DETECTED_PROPERTY:
            audio_monitor = self._audio_monitor
            self._audio_thrash_values.append((time.perf_counter(), value,
                                              audio_monitor.disengaged_age if value
                                              else audio_monitor.engaged_age
                                              ))
            self._update_state()
