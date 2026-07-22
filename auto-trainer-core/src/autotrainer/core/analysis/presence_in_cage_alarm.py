import math
from typing import Optional

from autotrainer.api import ApiAlarmKind
from autotrainer.core import get_perf_now
from autotrainer.core.analysis.alarm_detector import AlarmDetector
from autotrainer.core.configuration.presence_in_cage_config import PresenceInCageAlarmConfig
from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.pose_elements import ScenePartsPresenceContext
from autotrainer.core.video_detection import PresenceDetectionAttrs
from autotrainer.core.analysis.load_cell_monitor import LoadCellMonitor

logger = get_verbose_logger(__name__)


class PresenceInCageAlarm(AlarmDetector[PresenceInCageAlarmConfig]):

    config_cls = PresenceInCageAlarmConfig
    alarm_api_kind = ApiAlarmKind.animalMissing

    def __init__(
        self,
        *,
        load_cell_monitor: LoadCellMonitor,
        topcam_presence_attrs: Optional[PresenceDetectionAttrs] = None,
    ):
        super().__init__()
        self._all_scene_parts_ctx = ScenePartsPresenceContext()  # both/all cams seen
        self._load_cell_monitor = load_cell_monitor
        self._topcam_presence_attrs = topcam_presence_attrs
        load_cell_monitor.property_changed += self._on_load_cell_monitor_prop_changed

    def _check_state(self) -> Optional[float]:
        perf_now = get_perf_now()
        topcam = self._topcam_presence_attrs
        if topcam is None:
            return None
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
        prev = self._is_engaged
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
        self.is_engaged = engaged
        return None

    def update_parts_context(self, context: ScenePartsPresenceContext):
        self._all_scene_parts_ctx = context

    def _on_load_cell_monitor_prop_changed(self, name, value, _):
        self.check_state()
