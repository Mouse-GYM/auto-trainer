import math

from autotrainer.api import ApiAlarmKind
from autotrainer.core import get_perf_now
from autotrainer.core.analysis.alarm_detector import AlarmDetector
from autotrainer.core.configuration.animal_presence_configuration import GlobalAnimalPresenceConfig
from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.video_detection import PresenceDetectionAttrs
from autotrainer.core.analysis.load_cell_monitor import LoadCellMonitor

logger = get_verbose_logger(__name__)


class GlobalAnimalPresenceAlarm(AlarmDetector[GlobalAnimalPresenceConfig]):

    config_cls = GlobalAnimalPresenceConfig
    alarm_api_kind = ApiAlarmKind.animalImmobile

    use_daemon = True
    default_timer_delay = 60

    def __init__(
        self, *,
        load_cell_monitor: LoadCellMonitor,
        topcam_presence: PresenceDetectionAttrs,
    ):
        super().__init__()
        self._load_cell_monitor = load_cell_monitor
        self._topcam_presence = topcam_presence
        load_cell_monitor.property_changed += self._on_load_cell_property_changed
        # topcam presence has no property_changed. all purely shared values.

    def _on_load_cell_property_changed(self, name: str, value, old_value):
        if name == self._load_cell_monitor.IS_ENGAGED:
            self.check_state()

    def _check_state(self):
        perf_now = get_perf_now()
        cfg = self._config
        load_cell_mon = self._load_cell_monitor.context
        topcam_presence = self._topcam_presence
        if topcam_presence is None:
            logger.verbose("topcam presence is not configured")
            return None
        topcam_presence = topcam_presence.to_local_value()  # ensure consistency
        delay_seconds = cfg.presence_missing_delay_hours * 3600
        diff_started = perf_now - self._p_started
        if (
            diff_started < delay_seconds
            or load_cell_mon.is_engaged  # "weighted" currently in tunnel
            or topcam_presence.last_absence_start_perf_c < topcam_presence.last_presence_start_perf_c
                # "seen" currently in cage
        ):
            new_engaged = False
            if diff_started < delay_seconds:
                timer_delay = delay_seconds - diff_started
            else:
                timer_delay = delay_seconds
            top_cam_miss = math.nan
            load_cell_miss = math.nan
        else:
            top_cam_absence_age = perf_now - topcam_presence.last_absence_start_perf_c
            top_cam_miss = delay_seconds - top_cam_absence_age
            load_cell_miss = delay_seconds - load_cell_mon.disengaged_age
            if top_cam_miss <= 0 and load_cell_miss <= 0:
                new_engaged = True
                timer_delay = 1
            else:
                new_engaged = False
                timer_delay = max(top_cam_miss, load_cell_miss)
        if new_engaged != self._is_engaged:
            logger.verbose("engaged=%s top_cam_miss=%.1f load_cell_miss=%.1f ; new_delay=%.1f",
                         new_engaged, top_cam_miss, load_cell_miss, timer_delay)
        self.is_engaged = new_engaged
        return timer_delay
