import time
import math
import threading

from autotrainer.core import ObservableObject
from autotrainer.core.configuration.mouse_presence_configuration import GlobalMousePresenceConfig
from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.multiproc import no_op_timer, make_daemon_timer
from autotrainer.core.video_detection import PresenceDetectionAttrs
from autotrainer.core.analysis.load_cell_monitor import LoadCellMonitor

logger = get_verbose_logger(__name__)


class GlobalMousePresenceMonitor(ObservableObject):

    def __init__(
        self, *,
        config: GlobalMousePresenceConfig,
        load_cell_monitor: LoadCellMonitor,
        topcam_presence: PresenceDetectionAttrs,
    ):
        super().__init__()
        self._enabled = False
        self._is_engaged = False
        self._cur_timer = no_op_timer
        self._config = config
        self._lock = threading.RLock()
        self._load_cell_monitor = load_cell_monitor
        self._topcam_presence = topcam_presence
        self._t_started = -math.inf

    def start(self):
        logger.info("starting monitor")
        with self._lock:
            if self._enabled:
                return
            self._t_started = time.perf_counter()
            self._enabled = True
            # should we too:
            # self._is_engaged = False #  ?
            # to reset the current is_engaged state, and have a new one that will be generated(event)
            # if the trigger check(s) below turn to be true again ?
            timer = self._cur_timer = make_daemon_timer(0.1, self._check_state)
            timer.start()

    def stop(self, *, reason: str="na"):
        logger.info("stopping monitor: %s", reason)
        with self._lock:
            if not self._enabled:
                return
            self._enabled = False
            self._cur_timer.cancel()

    @property
    def config(self):
        return self._config

    @config.setter
    def config(self, value):
        self._config = value

    @property
    def is_engaged(self):
        """is_engaged == True means global mouse presence is missing"""
        return self._is_engaged

    @is_engaged.setter
    def is_engaged(self, value):
        # with self._lock:
        prev, self._is_engaged = self._is_engaged, value
        self._on_property_changed("is_engaged", value, prev)

    def _check_state(self):
        with self._lock:
            self.__check_state()

    def __check_state(self):
        if not self._enabled:
            logger.debug("not enabled")
            return
        # if self._is_engaged:
        #     return
        t_perf_now = time.perf_counter()
        top_cam_pres_age = t_perf_now - self._topcam_presence.last_presence_start_perf_c
        load_cell_mon = self._load_cell_monitor.context
        new_delay = 1
        cfg = self._config
        top_cam_miss = math.nan
        load_cell_miss = math.nan
        if load_cell_mon.is_engaged:
            self.is_engaged = False
        elif t_perf_now - self._t_started >  cfg.presence_missing_delay:
            top_cam_miss = cfg.presence_missing_delay - top_cam_pres_age
            load_cell_miss = cfg.presence_missing_delay - load_cell_mon.disengaged_age
            # if camera presence detections goes ON/triggered (shared value only)
            if top_cam_miss < 0 and load_cell_miss < 0:
                self.is_engaged = True
            else:
                self.is_engaged = False
                new_delay = max(top_cam_miss, load_cell_miss)
        logger.debug("engaged=%s top_cam_miss=%.1f load_cell_miss=%.1f new_delay=%.1f",
                     self._is_engaged, top_cam_miss, load_cell_miss, new_delay)
        #
        new_timer = self._cur_timer = make_daemon_timer(new_delay, self._check_state)
        new_timer.start()
