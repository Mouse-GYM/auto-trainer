import dataclasses
import enum
import math
from typing import Optional, List, Set, Callable

from autotrainer.api import ApiEventKind, ApiAlarmKind

from autotrainer.core import get_perf_now
from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.multiproc import make_daemon_timer
from autotrainer.core.pose_elements import ScenePartsPresenceContext
from autotrainer.core.video_detection import PresenceDetectionAttrs
from autotrainer.core.configuration.alarm_configuration import EmergencyAlarmConfiguration
from autotrainer.core.analysis.detector import BaseDetector
from autotrainer.core.analysis.external_doors_monitor import ExternalDoorsMonitor
from autotrainer.core.analysis.global_animal_presence_monitor import GlobalAnimalPresenceMonitor
from autotrainer.core.analysis.audio_spectrum_monitor import AudioSpectrumThrashMonitor
from autotrainer.core.analysis.load_cell_monitor import LoadCellMonitor
from autotrainer.core.analysis.load_cell_tare_monitor import LoadCellTareMonitor
from autotrainer.core.analysis.system_maintenance_monitor import SystemMaintenanceMonitor
from autotrainer.core.analysis.system_fault_monitor import SystemFaultMonitor


logger = get_verbose_logger(__name__)

timer_update_state = make_daemon_timer


class EmergencyReason(str, enum.Enum):

    MOUSE_THRASHING = "MOUSE_THRASHING"
    IN_CAGE_AFTER_EXIT_TUNNEL = "IN_CAGE_AFTER_EXIT_TUNNEL"
    DOORS_OPEN = "DOORS_OPEN"
    GLOBAL_ANIMAL_PRESENCE = "GLOBAL_ANIMAL_PRESENCE"
    DEVICE_COMM_ERROR = "DEVICE_COMM_ERROR"
    SYSTEM_MAINTENANCE = "SYSTEM_MAINTENANCE"
    SYSTEM_FAULT = "SYSTEM_FAULT"


_map_emergency_reason_2_api_alarm_kind = {
    EmergencyReason.MOUSE_THRASHING: ApiAlarmKind.thrashing,
    EmergencyReason.IN_CAGE_AFTER_EXIT_TUNNEL: ApiAlarmKind.animalMissing,
    EmergencyReason.GLOBAL_ANIMAL_PRESENCE: ApiAlarmKind.animalImmobile,
    EmergencyReason.DEVICE_COMM_ERROR: ApiAlarmKind.deviceCommunication,
    EmergencyReason.SYSTEM_FAULT: ApiAlarmKind.systemFault,
    EmergencyReason.SYSTEM_MAINTENANCE: ApiAlarmKind.systemMaintenance,
}

def emergency_reason_2_api_alarm_kind(reason: EmergencyReason) -> ApiAlarmKind:
    return _map_emergency_reason_2_api_alarm_kind[reason]



class EmergencyAlarmMonitor(BaseDetector):
    IS_ENGAGED = "is_engaged"
    CONFIG = "config"

    PRESENCE_IN_CAGE_AFTER_EXIT_TUNNEL_ENGAGED = "presence_in_cage_after_exit_tunnel_engaged"
    AUDIO_LOAD_CELL_THRASHING_ENGAGED = "audio_load_cell_thrashing_engaged"
    EXT_DOORS_OPEN_ENGAGED = "ext_doors_open_engaged"
    GLOBAL_ANIMAL_PRESENCE_ENGAGED = "global_animal_presence_engaged"
    DEVICE_COMM_ERROR_ENGAGED = "device_comm_error_engaged"
    SYSTEM_MAINTENANCE_ENGAGED = "system_maintenance_engaged"
    SYSTEM_FAULT_ENGAGED = "system_fault_engaged"

    use_daemon = True

    def __init__(
        self,
        *,
        config: EmergencyAlarmConfiguration,
        load_cell_monitor: LoadCellMonitor,
        load_cell_tare_monitor: LoadCellTareMonitor,
        audio_monitor: AudioSpectrumThrashMonitor,
        external_doors_monitor: ExternalDoorsMonitor,
        global_animal_presence_monitor: GlobalAnimalPresenceMonitor,
        system_maintenance_monitor: SystemMaintenanceMonitor,
        system_fault_monitor: SystemFaultMonitor,
        topcam_presence_attrs: Optional[PresenceDetectionAttrs] = None,
    ):
        super().__init__()
        self._running = True  # always
        self._all_scene_parts_ctx = ScenePartsPresenceContext()  # both/all cams seen
        self._config = config
        self._load_cell_monitor = load_cell_monitor
        self._load_cell_tare_monitor = load_cell_tare_monitor
        self._audio_monitor = audio_monitor
        self._external_doors_monitor = external_doors_monitor
        self._global_animal_presence_monitor = global_animal_presence_monitor
        self._system_maintenance_monitor = system_maintenance_monitor
        self._system_fault_monitor = system_fault_monitor
        self._topcam_presence_attrs = topcam_presence_attrs
        self._load_cell_thrash_values = []
        self._load_cell_engaged_values = []
        self._audio_thrash_values = []
        self._engaged_reasons: Set[EmergencyReason] = set()
        #
        self._audio_load_cell_thrashing_engaged = False
        self._presence_in_cage_after_exit_tunnel_engaged = False
        self._ext_doors_open_engaged = False
        self._global_animal_presence_engaged = False
        self._device_comm_error_engaged = False
        self._system_maintenance_engaged = False
        self._system_fault_engaged = False
        #
        load_cell_monitor.property_changed += self._on_load_cell_monitor_prop_changed
        audio_monitor.property_changed += self._on_audio_prop_changed
        external_doors_monitor.property_changed += self._on_ext_doors_prop_changed
        global_animal_presence_monitor.property_changed += self._on_global_animal_presence_prop_changed
        system_maintenance_monitor.property_changed += self._on_system_maintenance_prop_changed
        system_fault_monitor.property_changed += self._on_system_fault_prop_changed

    def stop(self):
        super().stop()
        self._running = True  # keep

    def update_parts_context(self, context: ScenePartsPresenceContext):
        self._all_scene_parts_ctx = context

    def add_alarm_condition(self, name, check):
        ...  # TODO

    def _start(self):
        super()._start()
        self._engaged_reasons.clear()

    def post_alarm_event(self, detector_id: int, active: bool, enabled: bool):
        self._event_manager.post_event_content(
            ApiEventKind.alarmChanged,
            data={
                "detector_id": detector_id,
                "is_active": active,
                "is_enabled": enabled,
            },
        )

    @property
    def config(self) -> EmergencyAlarmConfiguration:
        return self._config

    @config.setter
    def config(self, value: EmergencyAlarmConfiguration):
        prev, self._config = self._config, value
        self.property_changed(self.CONFIG, value, prev)

    @property
    def engaged_reasons(self) -> List[EmergencyReason]:
        return sorted(self._engaged_reasons)

    @property
    def audio_load_cell_thrashing_engaged(self):
        return self._audio_load_cell_thrashing_engaged

    @audio_load_cell_thrashing_engaged.setter
    def audio_load_cell_thrashing_engaged(self, value):
        prev, self._audio_load_cell_thrashing_engaged = self._audio_load_cell_thrashing_engaged, value
        if value == prev:
            return
        self.property_changed(self.AUDIO_LOAD_CELL_THRASHING_ENGAGED, value, prev)
        self.post_alarm_event(ApiAlarmKind.thrashing, value, self._config.use_audio_load_cell_thrash)
        self.check_state_if_not_detector_thread()

    @property
    def presence_in_cage_after_exit_tunnel_engaged(self):
        return self._presence_in_cage_after_exit_tunnel_engaged

    @presence_in_cage_after_exit_tunnel_engaged.setter
    def presence_in_cage_after_exit_tunnel_engaged(self, value):
        prev, self._presence_in_cage_after_exit_tunnel_engaged = self._presence_in_cage_after_exit_tunnel_engaged, value
        if value == prev:
            return
        self.property_changed(self.PRESENCE_IN_CAGE_AFTER_EXIT_TUNNEL_ENGAGED, value, prev)
        self.post_alarm_event(ApiAlarmKind.animalMissing, value, self._config.use_presence_missing_after_exit_tunnel)
        self.check_state_if_not_detector_thread()

    @property
    def ext_doors_open_engaged(self):
        return self._ext_doors_open_engaged

    @ext_doors_open_engaged.setter
    def ext_doors_open_engaged(self, value):
        prev, self._ext_doors_open_engaged = self._ext_doors_open_engaged, value
        if value == prev:
            return
        self.property_changed(self.EXT_DOORS_OPEN_ENGAGED, value, prev)
        self.post_alarm_event(ApiAlarmKind.externalDoors, value, self._config.use_external_doors_open)
        self.check_state_if_not_detector_thread()

    @property
    def global_animal_presence_engaged(self):
        return self._global_animal_presence_engaged

    @global_animal_presence_engaged.setter
    def global_animal_presence_engaged(self, value):
        prev, self._global_animal_presence_engaged = self._global_animal_presence_engaged, value
        if value == prev:
            return
        self.property_changed(self.GLOBAL_ANIMAL_PRESENCE_ENGAGED, value, prev)
        self.post_alarm_event(ApiAlarmKind.animalImmobile, value, self._config.use_global_animal_presence)
        self.check_state_if_not_detector_thread()

    @property
    def device_comm_error_engaged(self):
        return self._device_comm_error_engaged

    @device_comm_error_engaged.setter
    def device_comm_error_engaged(self, value):
        # is set/unset from hardware model
        prev, self._device_comm_error_engaged = self._device_comm_error_engaged, value
        if value == prev:
            return
        self.property_changed(self.DEVICE_COMM_ERROR_ENGAGED, value, prev)
        self.post_alarm_event(ApiAlarmKind.deviceCommunication, value, self._config.use_device_comm_error)
        self.check_state_if_not_detector_thread()

    @property
    def system_maintenance_engaged(self):
        return self._system_maintenance_engaged

    @system_maintenance_engaged.setter
    def system_maintenance_engaged(self, value):
        prev, self._system_maintenance_engaged = self._system_maintenance_engaged, value
        if value == prev:
            return
        self.property_changed(self.SYSTEM_MAINTENANCE_ENGAGED, value, prev)
        self.post_alarm_event(ApiAlarmKind.systemMaintenance, value, self._config.use_system_maintenance)
        self.check_state_if_not_detector_thread()

    @property
    def system_fault_engaged(self):
        return self._system_fault_engaged

    @system_fault_engaged.setter
    def system_fault_engaged(self, value):
        prev, self._system_fault_engaged = self._system_fault_engaged, value
        if value == prev:
            return
        self.property_changed(self.SYSTEM_FAULT_ENGAGED, value, prev)
        self.post_alarm_event(ApiAlarmKind.systemFault, value, self._config.use_system_fault)
        self.check_state_if_not_detector_thread()

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
        elif self._audio_monitor.thrashing_detected:
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
        topcam = self._topcam_presence_attrs
        if topcam is None:
            return False
        topcam = topcam.to_local_value()  # to ensure consistent lookups
        load_cell = self._load_cell_monitor.context
        cfg = self._config
        pres_ctx = self._all_scene_parts_ctx
        tun_pres_age = pres_ctx.get_animal_presence_age(perf_now=perf_now)
        tun_miss_age = pres_ctx.get_animal_absence_age(perf_now=perf_now)
        engaged = (
                not load_cell.is_engaged  # ~= not in tunnel
            and load_cell.last_disengaged_perf_c > self._p_started
            and perf_now - load_cell.last_disengaged_perf_c > cfg.tunnel_to_cage_presence_missing_delay
                # tunnel exited at least since missing delay threshold
            and tun_pres_age >= 0
            and perf_now - tun_pres_age > load_cell.last_engaged_perf_c
                # animal was seen in tunnel in last tunnel activity/session
            and (
                # last top-cam presence must be before the current load cell disengaged:
                topcam.last_presence_start_perf_c < load_cell.last_disengaged_perf_c
                and topcam.last_absence_start_perf_c < load_cell.last_disengaged_perf_c
                    # the previous presence detection in topcam could be right before the exit tunnel,
                    # this check ensures the topcam last absence is before last disengage
                and (
                    topcam.last_presence_start_perf_c
                    < topcam.last_absence_start_perf_c  # currently absent from topcam
                    < perf_now - cfg.tunnel_to_cage_presence_missing_delay
                    # and that absence duration is greater than the missing delay threshold
                )
            )
        )
        prev = self._presence_in_cage_after_exit_tunnel_engaged
        if engaged and not prev:
            meth = logger.notice
        elif not engaged and prev:
            meth = logger.success
        else:
            meth = None
        if meth is not None:
            meth(
                "Presence-in-cage %s. lc=%s lc.last_eng=%s lc.last_dis=%s "
                "tun_pres_age=%s tun_miss_age=%s "
                "top.last_pres=%s top.last_abs=%s",
                "engaged" if engaged else "disengaged",
                load_cell.is_engaged, load_cell.last_engaged_perf_c, load_cell.last_disengaged_perf_c,
                tun_pres_age, tun_miss_age,
                topcam.last_presence_start_perf_c, topcam.last_absence_start_perf_c)
        return engaged

    def _check_state(self):
        topcam_attrs = self._topcam_presence_attrs
        load_cell = self._load_cell_monitor.context
        cfg = self._config
        perf_now = get_perf_now()
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
        self.global_animal_presence_engaged = self._global_animal_presence_monitor.is_engaged
        if self._global_animal_presence_engaged and cfg.use_global_animal_presence:
            reasons.add(EmergencyReason.GLOBAL_ANIMAL_PRESENCE)
        #
        if self._device_comm_error_engaged and cfg.use_device_comm_error:
            reasons.add(EmergencyReason.DEVICE_COMM_ERROR)
        #
        self.system_maintenance_engaged = self._system_maintenance_monitor.is_engaged
        if self._system_maintenance_engaged and cfg.use_system_maintenance:
            reasons.add(EmergencyReason.SYSTEM_MAINTENANCE)
        #
        self.system_fault_engaged = self._system_fault_monitor.is_engaged
        if self._system_fault_engaged and cfg.use_system_fault:
            reasons.add(EmergencyReason.SYSTEM_FAULT)
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
        add_remove_map = {
            EmergencyReason.MOUSE_THRASHING: cfg.auto_resume_on_audio_load_cell_thrash_resume,
            EmergencyReason.IN_CAGE_AFTER_EXIT_TUNNEL: cfg.auto_resume_on_presence_seen_after_exit_tunnel,
            EmergencyReason.DOORS_OPEN: cfg.auto_resume_on_external_doors_close,
            EmergencyReason.GLOBAL_ANIMAL_PRESENCE: cfg.auto_resume_on_global_animal_presence,
            EmergencyReason.DEVICE_COMM_ERROR: cfg.auto_resume_on_device_comm_error,
            EmergencyReason.SYSTEM_MAINTENANCE: cfg.auto_resume_on_system_maintenance,
            EmergencyReason.SYSTEM_FAULT: cfg.auto_resume_on_system_fault,
        }
        #
        if not is_emergency:
            check_reasons = self._engaged_reasons.copy()
            # look if previous engaged reasons (which are now cleared), allowed auto-resume, or not.
            # if any does not allow : don't remove the is_engaged.
            for prev_r in list(check_reasons):
                if add_remove_map[prev_r]:
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
                if not add_remove_map[prev_r]:
                    reasons.add(prev_r)
            if reasons != self._engaged_reasons:
                self._is_engaged = None  # force trigger again, so that new reasons are seen
                self._engaged_reasons = reasons
            self.is_engaged = True
        return 1  # timer_delay

    def _on_load_cell_monitor_prop_changed(self, name, value, _):
        if not self._running:
            return
        if not self._config.use_audio_load_cell_thrash:
            return
        if name == LoadCellMonitor.IS_THRASHING_DETECTED_PROPERTY:
            perf_now = get_perf_now()
            load_cell = self._load_cell_monitor.context
            with self._lock:
                self._load_cell_thrash_values.append((perf_now, value,
                                                      load_cell.thrashing_disengaged_age if value
                                                      else load_cell.thrashing_engaged_age))
            self.check_state()
        elif name == LoadCellMonitor.IS_ENGAGED_PROPERTY:
            self.check_state()

    def _on_audio_prop_changed(self, name, value, _):
        if not self._running:
            return
        if not self._config.use_audio_load_cell_thrash:
            return
        if name == AudioSpectrumThrashMonitor.AUDIO_THRASHING_DETECTED_PROPERTY:
            audio_monitor = self._audio_monitor
            with self._lock:
                self._audio_thrash_values.append((get_perf_now(), value,
                                                  audio_monitor.disengaged_age if value
                                                  else audio_monitor.engaged_age
                                                  ))
            self.check_state()

    def _on_ext_doors_prop_changed(self, name, value, _):
        if not self._running:
            return
        if not self._config.use_external_doors_open:
            return
        if name == ExternalDoorsMonitor.IS_ENGAGED:
            self.check_state()

    def _on_global_animal_presence_prop_changed(self, name, value, _):
        if not self._running:
            return
        if not self._config.use_global_animal_presence:
            return
        if name == GlobalAnimalPresenceMonitor.IS_ENGAGED:
            self.check_state()

    def _on_system_maintenance_prop_changed(self, name, value, _):
        self.check_state()

    def _on_system_fault_prop_changed(self, name, value, _):
        self.check_state()
