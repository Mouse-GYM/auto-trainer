
from typing import List, Tuple, Optional

from autotrainer.api import ApiAlarmKind
from autotrainer.core import get_perf_now
from autotrainer.core.analysis.alarm_detector import AlarmDetector
from autotrainer.core.analysis.audio_spectrum_monitor import AudioSpectrumThrashMonitor
from autotrainer.core.analysis.load_cell_monitor import LoadCellMonitor
from autotrainer.core.configuration.animal_thrash_config import AnimalThrashAlarmConfig


class AnimalThrashAlarm(AlarmDetector[AnimalThrashAlarmConfig]):

    config_cls = AnimalThrashAlarmConfig
    alarm_api_kind = ApiAlarmKind.thrashing

    use_daemon = True
    default_timer_delay = 1

    def __init__(
        self,
        *,
        load_cell_detector: LoadCellMonitor,
        audio_thrash_detector: AudioSpectrumThrashMonitor,
    ):
        super().__init__()
        self._load_cell_det = load_cell_detector
        self._audio_thrash_det = audio_thrash_detector
        #
        self._load_cell_thrash_values: List[Tuple[float, bool, float]] = []  # perf_c, engaged, age
        self._audio_thrash_values: List[Tuple[float, bool, float]]  = []
        #
        audio_thrash_detector.property_changed += self._on_audio_prop_changed
        load_cell_detector.property_changed += self._on_load_cell_prop_changed

    def _on_audio_prop_changed(self, name, value, _):
        if not self._running:  # keep check to not append values below
            return
        det = self._audio_thrash_det
        if name == det.IS_ENGAGED:
            with self._lock:
                self._audio_thrash_values.append((get_perf_now(), value,
                                                  det.disengaged_age if value
                                                  else det.engaged_age
                                                  ))
            self.check_state()

    def _on_load_cell_prop_changed(self, name, value, _):
        if not self._running:  # keep check to not append values below
            return
        if name == LoadCellMonitor.IS_THRASHING_DETECTED_PROPERTY:
            perf_now = get_perf_now()
            load_cell = self._load_cell_det.context
            with self._lock:
                self._load_cell_thrash_values.append((perf_now, value,
                                                      load_cell.thrashing_disengaged_age if value
                                                      else load_cell.thrashing_engaged_age))
            self.check_state()

    def _expire_audio_load_cell(self, perf_now):
        cfg = self._config
        for values in (self._load_cell_thrash_values, self._audio_thrash_values):
            idx = len(values) - 1
            while idx >= 0:
                t_perf = values[idx][0]
                if perf_now - t_perf > cfg.aggregate_delay:
                    del values[:idx + 1]
                    break
                idx -= 1

    def _check_state(self):
        perf_now = get_perf_now()
        self._expire_audio_load_cell(perf_now)
        cfg: AnimalThrashAlarmConfig = self._config
        load_cell = self._load_cell_det.context
        count_load_cell_thrash_triggers = 0  # count
        tot_load_cell_thrash_engaged = 0  # seconds
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
        elif load_cell.thrashing_detected:
            tot_load_cell_thrash_engaged += cfg.aggregate_delay
        #
        count_audio_thrash_triggers = 0  # count
        tot_audio_thrash_engaged = 0  # seconds
        v: Optional[Tuple[float, bool, float]] = None
        for idx, v in enumerate(self._audio_thrash_values):
            if v[1]:
                count_audio_thrash_triggers += 1
            else:
                tot_audio_thrash_engaged += (v[0] - perf_c_start) if idx == 0 else v[2]
        if v is not None:
            if v[1]:
                tot_audio_thrash_engaged += perf_now - v[0]
        elif self._audio_thrash_det.is_engaged:
            tot_audio_thrash_engaged += cfg.aggregate_delay
        #
        pc_load_cell_thrash = (
            100 * tot_load_cell_thrash_engaged / cfg.aggregate_delay
        )
        pc_audio_thrash = (
            100 * tot_audio_thrash_engaged / cfg.aggregate_delay
        )
        #
        engaged = (
            pc_load_cell_thrash >= cfg.load_cell_thrash_percent_on
            or count_load_cell_thrash_triggers >= cfg.load_cell_thrash_count
        ) and (
            pc_audio_thrash >= cfg.audio_thrash_percent_on
            or count_audio_thrash_triggers >= cfg.audio_thrash_count
        )
        self.is_engaged = engaged
