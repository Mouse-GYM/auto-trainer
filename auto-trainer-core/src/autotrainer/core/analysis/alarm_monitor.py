import enum
import math
import threading
import time
from typing import Optional, List, Set

from autotrainer.core import ObservableObject
from autotrainer.core.analysis.detector import BaseDetector
from autotrainer.core.analysis.external_doors_monitor import ExternalDoorsMonitor
from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.multiproc import no_op_timer, make_daemon_timer
from autotrainer.core.video_detection import PresenceDetectionAttrs
from autotrainer.core.configuration.alarm_configuration import EmergencyAlarmConfiguration
from autotrainer.core.analysis.audio_spectrum_monitor import AudioSpectrumThrashMonitor
from autotrainer.core.analysis.load_cell_monitor import LoadCellMonitor

logger = get_verbose_logger(__name__)

timer_update_state = make_daemon_timer


class EmergencyReason(str, enum.Enum):

    MOUSE_THRASHING = "MOUSE_THRASHING"
    IN_CAGE_AFTER_EXIT_TUNNEL = "IN_CAGE_AFTER_EXIT_TUNNEL"
    DOORS_OPEN = "DOORS_OPEN"


class EmergencyAlarmMonitor(BaseDetector):

    IS_ENGAGED = "is_engaged"
    CONFIG = "config"
    PRESENCE_IN_CAGE_AFTER_EXIT_TUNNEL_ENGAGED = "presence_in_cage_after_exit_tunnel_engaged"
    AUDIO_LOAD_CELL_THRASHING_ENGAGED = "audio_load_cell_thrashing_engaged"
    EXT_DOORS_OPEN_ENGAGED = "ext_doors_open_engaged"

    def __init__(
        self,
        *,
        config: EmergencyAlarmConfiguration,
        load_cell_monitor: LoadCellMonitor,
        audio_monitor: AudioSpectrumThrashMonitor,
        external_doors_monitor: ExternalDoorsMonitor,
        topcam_presence_attrs: Optional[PresenceDetectionAttrs] = None,
    ):
        super().__init__()
        self._config = config
        self._load_cell_monitor = load_cell_monitor
        self._audio_monitor = audio_monitor
        self._external_doors_monitor = external_doors_monitor
        self._topcam_presence_attrs = topcam_presence_attrs
        self._load_cell_thrash_values = []
        self._load_cell_engaged_values = []
        self._audio_thrash_values = []
        self._engaged_reasons: Set[EmergencyReason] = set()
        self._audio_load_cell_thrashing_engaged = False
        self._presence_in_cage_after_exit_tunnel_engaged = False
        self._ext_doors_open_engaged = False
        load_cell_monitor.property_changed += self._load_cell_monitor_prop_changed
        audio_monitor.property_changed += self._audio_prop_changed

    def _start(self):
        super()._start()
        self._engaged_reasons.clear()

    @property
    def config(self) -> EmergencyAlarmConfiguration:
        return self._config

    @config.setter
    def config(self, value: EmergencyAlarmConfiguration):
        prev, self._config = self._config, value
        self.property_changed(self.CONFIG, value, prev)

    @property
    def engaged_reasons(self) -> List[str]:
        return sorted(reason.name for reason in self._engaged_reasons)

    @property
    def audio_load_cell_thrashing_engaged(self):
        return self._audio_load_cell_thrashing_engaged

    @audio_load_cell_thrashing_engaged.setter
    def audio_load_cell_thrashing_engaged(self, value):
        prev, self._audio_load_cell_thrashing_engaged = self._audio_load_cell_thrashing_engaged, value
        self._on_property_changed(self.AUDIO_LOAD_CELL_THRASHING_ENGAGED, value, prev)

    @property
    def presence_in_cage_after_exit_tunnel_engaged(self):
        return self._presence_in_cage_after_exit_tunnel_engaged

    @presence_in_cage_after_exit_tunnel_engaged.setter
    def presence_in_cage_after_exit_tunnel_engaged(self, value):
        prev, self._presence_in_cage_after_exit_tunnel_engaged = self._presence_in_cage_after_exit_tunnel_engaged, value
        self._on_property_changed(self.PRESENCE_IN_CAGE_AFTER_EXIT_TUNNEL_ENGAGED, value, prev)

    @property
    def ext_doors_open_engaged(self):
        return self._ext_doors_open_engaged

    @ext_doors_open_engaged.setter
    def ext_doors_open_engaged(self, value):
        prev, self._ext_doors_open_engaged = self._ext_doors_open_engaged, value
        self._on_property_changed(self.EXT_DOORS_OPEN_ENGAGED, value, prev)

    #
    def _expire_audio_load_cell(self, perf_now):
        cfg = self._config
        for values in (self._load_cell_thrash_values, self._audio_thrash_values):
            idx = len(values) - 1
            while idx >= 0:
                t_perf = values[idx][0]
                if perf_now - t_perf > cfg.audio_load_cell_thrash_aggregate_delay:
                    del values[:idx + 1]
                    break
                idx -= 1

    def _check_audio_load_cell(self, perf_now):
        self._expire_audio_load_cell(perf_now)
        cfg = self._config
        load_cell = self._load_cell_monitor.context
        count_load_cell_thrash_triggers = 0  # count
        tot_load_cell_thrash_engaged = 0  # seconds
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
        elif load_cell.thrashing_detected:
            tot_load_cell_thrash_engaged += cfg.audio_load_cell_thrash_aggregate_delay
        #
        count_audio_thrash_triggers = 0  # count
        tot_audio_thrash_engaged = 0  # seconds
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
        return (
            (
                pc_load_cell_thrash >= cfg.load_cell_thrash_percent_on
                or count_load_cell_thrash_triggers >= cfg.load_cell_thrash_count
            ) and (
                pc_audio_thrash >= cfg.audio_thrash_percent_on
                or count_audio_thrash_triggers >= cfg.audio_thrash_count
            )
        )

    def _check_pres_after_exit_tunnel_missing(self, perf_now):
        topcam_attrs = self._topcam_presence_attrs
        load_cell = self._load_cell_monitor.context
        cfg = self._config
        return (
            topcam_attrs is not None
            and not load_cell.is_engaged
            and load_cell.last_disengaged_perf_c > self._t_started
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

    def _check_state(self):
        topcam_attrs = self._topcam_presence_attrs
        load_cell = self._load_cell_monitor.context
        cfg = self._config
        perf_now = time.perf_counter()
        #
        reasons = set()
        #
        self.audio_load_cell_thrashing_engaged = self._check_audio_load_cell(perf_now)
        if self._audio_load_cell_thrashing_engaged and cfg.use_audio_load_cell_thrash:
            reasons.add(EmergencyReason.MOUSE_THRASHING)
        #
        self.presence_in_cage_after_exit_tunnel_engaged = self._check_pres_after_exit_tunnel_missing(perf_now)
        if self._presence_in_cage_after_exit_tunnel_engaged and cfg.use_presence_missing_after_exit_tunnel:
            reasons.add(EmergencyReason.IN_CAGE_AFTER_EXIT_TUNNEL)
        #
        self.ext_doors_open_engaged = self._external_doors_monitor.is_engaged
        if self._ext_doors_open_engaged and cfg.use_external_doors_open:
            reasons.add(EmergencyReason.DOORS_OPEN)
        #
        is_emergency = len(reasons) > 0
        #
        if is_emergency and not self._is_engaged:
            logger.notice("Engaging emergency: %s", reasons)
            if __debug__:
                logger.debug("load_cell.disengaged_age=%.1f"
                    " load_cell.engaged_age=%.1f presence_start_perf_c=%.1f absence_start_perf_c=%.1f perf_now=%.1f",
                    load_cell.disengaged_age, load_cell.engaged_age,
                    *((math.nan, math.nan) if topcam_attrs is None else (topcam_attrs.last_presence_start_perf_c, topcam_attrs.last_absence_start_perf_c)),
                    perf_now)
        elif __debug__:
            logger.spam(
                "is_emergency=%s load_cell.disengaged_age=%.1f"
                " load_cell.engaged_age=%.1f presence_start_perf_c=%.1f absence_start_perf_c=%.1f perf_now=%.1f",
                is_emergency,
                load_cell.disengaged_age, load_cell.engaged_age,
                *((math.nan, math.nan) if topcam_attrs is None else (topcam_attrs.last_presence_start_perf_c, topcam_attrs.last_absence_start_perf_c)),
                perf_now)
        #
        if not is_emergency:
            check_reasons = self._engaged_reasons.copy()
            # look if previous engaged reasons (which are now cleared), allowed auto-resume, or not.
            # if any does not allow : don't remove the is_engaged.
            for prev_r in list(check_reasons):
                if ((prev_r == EmergencyReason.MOUSE_THRASHING and cfg.auto_resume_on_audio_load_cell_thrash_resume)
                 or (prev_r == EmergencyReason.IN_CAGE_AFTER_EXIT_TUNNEL and cfg.auto_resume_on_presence_seen_after_exit_tunnel)
                 or (prev_r == EmergencyReason.DOORS_OPEN and cfg.auto_resume_on_external_doors_close)
                ):
                    check_reasons.remove(prev_r)
            #
            if len(check_reasons) == 0:
                self.is_engaged = False
            self._engaged_reasons = check_reasons  # always reset with what remains in check_reasons.
        else:
            check_reasons = self._engaged_reasons.copy()
            # if some possible condition were previously present and are not auto-resume enabled,
            # then re-add them to current reasons of engaged.
            for prev_r in list(check_reasons):
                if ((
                    prev_r == EmergencyReason.MOUSE_THRASHING
                    and not cfg.auto_resume_on_audio_load_cell_thrash_resume
                ) or (
                    prev_r == EmergencyReason.IN_CAGE_AFTER_EXIT_TUNNEL
                    and not cfg.auto_resume_on_presence_seen_after_exit_tunnel
                ) or (
                    prev_r == EmergencyReason.DOORS_OPEN
                    and not cfg.auto_resume_on_external_doors_close
                )):
                    reasons.add(prev_r)
            self._engaged_reasons = reasons
            self.is_engaged = True
        return 1  # timer_delay

    def _load_cell_monitor_prop_changed(self, name, value, _):
        if not self._enabled:
            return
        if not self._config.use_audio_load_cell_thrash:
            return
        if name == LoadCellMonitor.IS_THRASHING_DETECTED_PROPERTY:
            perf_now = time.perf_counter()
            load_cell = self._load_cell_monitor.context
            with self._lock:
                self._load_cell_thrash_values.append((perf_now, value,
                                                      load_cell.thrashing_disengaged_age if value
                                                      else load_cell.thrashing_engaged_age))
            self.check_state()
        elif name == LoadCellMonitor.IS_ENGAGED_PROPERTY:
            self.check_state()

    def _audio_prop_changed(self, name, value, _):
        if not self._enabled:
            return
        if not self._config.use_audio_load_cell_thrash:
            return
        if name == AudioSpectrumThrashMonitor.AUDIO_THRASHING_DETECTED_PROPERTY:
            audio_monitor = self._audio_monitor
            with self._lock:
                self._audio_thrash_values.append((time.perf_counter(), value,
                                                  audio_monitor.disengaged_age if value
                                                  else audio_monitor.engaged_age
                                                  ))
            self.check_state()

    def _ext_doors_prop_changed(self, name, value, _):
        if name == ExternalDoorsMonitor.IS_ENGAGED:
            self.check_state()
