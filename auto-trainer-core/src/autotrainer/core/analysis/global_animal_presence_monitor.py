import os
import time
import math
import threading

from autotrainer.core import ObservableObject, get_perf_now
from autotrainer.core.analysis.detector import BaseDetector
from autotrainer.core.configuration.animal_presence_configuration import GlobalAnimalPresenceConfig
from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.multiproc import no_op_timer, make_daemon_timer
from autotrainer.core.video_detection import PresenceDetectionAttrs
from autotrainer.core.analysis.load_cell_monitor import LoadCellMonitor

logger = get_verbose_logger(__name__)


class GlobalAnimalPresenceMonitor(BaseDetector):

    use_daemon = True
    feature_enabled = True

    def __init__(
        self, *,
        config: GlobalAnimalPresenceConfig,
        load_cell_monitor: LoadCellMonitor,
        topcam_presence: PresenceDetectionAttrs,
    ):
        super().__init__()
        self._config = config
        self._load_cell_monitor = load_cell_monitor
        self._topcam_presence = topcam_presence

    @property
    def config(self):
        return self._config

    @config.setter
    def config(self, value):
        self._config = value

    def _check_state(self):
        t_perf_now = get_perf_now()
        cfg = self._config
        load_cell_mon = self._load_cell_monitor.context
        topcam_presence = self._topcam_presence
        if topcam_presence is None:
            logger.verbose("topcam presence is not configured")
            return None
        top_cam_pres_age = t_perf_now - topcam_presence.last_presence_start_perf_c
        delay_seconds = cfg.presence_missing_delay_hours * 3600
        timer_delay = 1
        diff_started = t_perf_now - self._t_started
        if diff_started < delay_seconds or load_cell_mon.is_engaged:
            new_engaged = False
            if diff_started < delay_seconds:
                timer_delay = delay_seconds - diff_started
            top_cam_miss = math.nan
            load_cell_miss = math.nan
        else:
            top_cam_miss = delay_seconds - top_cam_pres_age
            load_cell_miss = delay_seconds - load_cell_mon.disengaged_age
            if top_cam_miss <= 0 and load_cell_miss <= 0:
                new_engaged = True
            else:
                new_engaged = False
                timer_delay = max(top_cam_miss, load_cell_miss)
        logger.debug("engaged=%s top_cam_miss=%.1f load_cell_miss=%.1f ; new_delay=%.1f",
                     new_engaged, top_cam_miss, load_cell_miss, timer_delay)
        self.is_engaged = new_engaged
        return timer_delay
