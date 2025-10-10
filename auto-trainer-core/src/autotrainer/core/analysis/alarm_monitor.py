import math
import time
from typing import Optional

from autotrainer.core import ObservableObject, LoadCellMonitor, get_verbose_logger
from autotrainer.core.analysis.audio_spectrum_monitor import AudioSpectrumThrashMonitor
from autotrainer.core.configuration.alarm_configuration import EmergencyAlarmConfiguration
from autotrainer.core.multiproc import no_op_timer, make_daemon_timer
from autotrainer.core.video_detection import PresenceDetectionAttrs


logger = get_verbose_logger(__name__)

timer_update_state = make_daemon_timer


class EmergencyAlarmMonitor(ObservableObject):

    def __init__(
        self,
        *,
        config: EmergencyAlarmConfiguration,
        load_cell_monitor: LoadCellMonitor,
        audio_monitor: AudioSpectrumThrashMonitor,
        topcam_presence_attrs: Optional[PresenceDetectionAttrs] = None,
    ):
        super().__init__()
        self._config = config
        self._load_cell_monitor = load_cell_monitor
        self._audio_monitor = audio_monitor
        self._topcam_presence_attrs = topcam_presence_attrs
        self._load_cell_thrash_values = []
        self._load_cell_engaged_values = []
        self._audio_thrash_values = []
        self._is_engaged = False
        self._timer_update_state = no_op_timer
        self._prev_audio_load_cell_thrash_alarm: bool = False
        self._prev_pres_miss_after_exit_tunnel_alarm: bool = False
        load_cell_monitor.property_changed += self._load_cell_monitor_prop_changed
        audio_monitor.property_changed += self._audio_prop_changed

    @property
    def config(self):
        return self._config

    @config.setter
    def config(self, value):
        self._config = value

    @property
    def is_engaged(self):
        return self._is_engaged

    @is_engaged.setter
    def is_engaged(self, value):
        prev, self._is_engaged = self._is_engaged, value
        self._on_property_changed("is_engaged", value, prev)

    def _update_state(self):
        topcam_attrs = self._topcam_presence_attrs
        load_cell = self._load_cell_monitor
        self._timer_update_state.cancel()
        cfg = self._config
        perf_now = time.perf_counter()
        #
        for values in (self._load_cell_engaged_values, self._load_cell_thrash_values, self._audio_thrash_values):
            idx = len(values) - 1
            while idx >= 0:
                t_perf = values[idx][0]
                if perf_now - t_perf > cfg.audio_load_cell_thrash_aggregate_delay:
                    del values[:idx + 1]
                    break
                idx -= 1
        #
        count_load_cell_thrash_triggers = 0
        tot_load_cell_thrash_engaged = 0
        v = None
        perf_c_start = perf_now - cfg.audio_load_cell_thrash_aggregate_delay

        for idx, v in enumerate(self._load_cell_thrash_values):
            if v[1]:
                count_load_cell_thrash_triggers += 1
            else:
                tot_load_cell_thrash_engaged += (v[0] - perf_c_start) if idx == 0 else v[2]
        if v is not None:
            if v[1]:
                tot_load_cell_thrash_engaged += perf_now - v[0]
        elif self._load_cell_monitor.thrashing_detected:
            tot_load_cell_thrash_engaged += cfg.audio_load_cell_thrash_aggregate_delay
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
            tot_audio_thrash_engaged += cfg.audio_load_cell_thrash_aggregate_delay
        #
        pc_load_cell_thrash = 100 * tot_load_cell_thrash_engaged / cfg.audio_load_cell_thrash_aggregate_delay
        pc_audio_thrash = 100 * tot_audio_thrash_engaged / cfg.audio_load_cell_thrash_aggregate_delay
        #
        audio_load_cell_thrash_alarm = (
            (
                pc_load_cell_thrash >= cfg.load_cell_thrash_percent_on
                or count_load_cell_thrash_triggers >= cfg.load_cell_thrash_count
            ) and (
                pc_audio_thrash >= cfg.audio_thrash_percent_on
                or count_audio_thrash_triggers >= cfg.audio_thrash_count
            )
        )
        #
        pres_missing_after_exit_tunnel_alarm = (
            topcam_attrs is not None
            and not load_cell.is_engaged
            and load_cell.disengaged_age > cfg.tunnel_to_cage_presence_missing_delay
            and (
                # last presence must be before the current load cell disengaged:
                topcam_attrs.last_presence_start_perf_c < perf_now - load_cell.disengaged_age
                and (
                    topcam_attrs.last_presence_start_perf_c
                    < topcam_attrs.last_absence_start_perf_c
                    < perf_now - cfg.tunnel_to_cage_presence_missing_delay
                )
            )
        )
        #
        is_emergency = (
               (cfg.use_audio_load_cell_thrash and audio_load_cell_thrash_alarm)
            or (cfg.use_presence_missing_after_exit_tunnel and pres_missing_after_exit_tunnel_alarm)
        )
        #
        if is_emergency and not self._is_engaged:
            logger.notice("Engaging emergency: pc_load_cell_thrash=%.1f pc_audio_thrash=%.1f load_cell.disengaged_age=%.1f"
                " load_cell.engaged_age=%.1f presence_start_perf_c=%.1f absence_start_perf_c=%.1f perf_now=%.1f",
                pc_load_cell_thrash, pc_audio_thrash,
                load_cell.disengaged_age, load_cell.engaged_age,
                *((math.nan, math.nan) if topcam_attrs is None else (topcam_attrs.last_presence_start_perf_c, topcam_attrs.last_absence_start_perf_c)),
                perf_now)
        elif __debug__:
            logger.spam(
                "is_emergency=%s pc_load_cell_thrash=%.1f pc_audio_thrash=%.1f load_cell.disengaged_age=%.1f"
                " load_cell.engaged_age=%.1f presence_start_perf_c=%.1f absence_start_perf_c=%.1f perf_now=%.1f",
                is_emergency, pc_load_cell_thrash, pc_audio_thrash,
                load_cell.disengaged_age, load_cell.engaged_age,
                *((math.nan, math.nan) if topcam_attrs is None else (topcam_attrs.last_presence_start_perf_c, topcam_attrs.last_absence_start_perf_c)),
                perf_now)
        #
        if self._is_engaged and not is_emergency:
            auto_disengage = ((
                cfg.use_audio_load_cell_thrash
                and self._prev_audio_load_cell_thrash_alarm
                and cfg.auto_resume_on_audio_load_cell_thrash_resume
            ) or (
                cfg.use_presence_missing_after_exit_tunnel
                and self._prev_pres_miss_after_exit_tunnel_alarm
                and cfg.auto_resume_on_presence_seen_after_exit_tunnel
            ))
            if auto_disengage:
                self.is_engaged = False
                self._prev_pres_miss_after_exit_tunnel_alarm = self._prev_audio_load_cell_thrash_alarm = False
        #
        else:
            self.is_engaged = is_emergency
            self._prev_audio_load_cell_thrash_alarm = audio_load_cell_thrash_alarm
            self._prev_pres_miss_after_exit_tunnel_alarm = pres_missing_after_exit_tunnel_alarm

        if not is_emergency and (
            topcam_attrs is None
            or topcam_attrs.last_presence_start_perf_c >= perf_now - load_cell.disengaged_age
        ):
            logger.verbose("Not restarting timer given topcam last_presence is more recent than load_cell disengaged")
        else:
            timer = self._timer_update_state = timer_update_state(1, self._update_state)
            timer.start()

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

    def _audio_prop_changed(self, name, value, _):
        if name == AudioSpectrumThrashMonitor.AUDIO_THRASHING_DETECTED_PROPERTY:
            audio_monitor = self._audio_monitor
            self._audio_thrash_values.append((time.perf_counter(), value,
                                              audio_monitor.disengaged_age if value
                                              else audio_monitor.engaged_age
                                              ))
            self._update_state()
