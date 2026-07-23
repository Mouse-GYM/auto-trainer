from typing import Optional, Set, List

from datetime import date, datetime, timedelta

from autotrainer.api import ApiDetectorKind, ApiAlarmKind

from autotrainer.core.logging import get_verbose_logger
from .alarm_detector import AlarmDetector

from ..configuration.system_maintenance_config import SystemMaintenanceConfig


logger = get_verbose_logger(__name__)


class SystemMaintenanceAlarm(AlarmDetector[SystemMaintenanceConfig]):
    # could be todo: also convert to GroupBaseDetector + AlarmDetector,
    # with new 3 sub-detectors:
    # 1) max-pellet-loaded
    # 2) max-consecutive-failed-load
    # 3) cage-need-clean

    config_cls = SystemMaintenanceConfig
    alarm_api_kind = ApiAlarmKind.systemMaintenance

    use_daemon = True
    default_timer_delay = 60  # do really not need precise, but once every minute is quite good.

    MAX_PELLET_LOADED_ENGAGED = "max_pellet_loaded_engaged"
    MAX_CONSECUTIVE_FAILED_LOAD_ENGAGED = "max_consecutive_failed_load_engaged"
    CAGE_NEED_CLEAN_ENGAGED = "cage_need_clean_engaged"

    def __init__(self):
        super().__init__()
        self._max_pellet_loaded_engaged = False
        self._max_consecutive_failed_load_engaged = False
        self._cage_need_clean_engaged = False
        self._cage_clean_next_day: date = date.today() + timedelta(days=7)
        # NB: default cage_clean_next_day must be at least after tomorrow,
        # otherwise, given default cage_need_clean_look_ahead_hours of 4h,
        # if some test case are executed after 20h localtime,
        # then that breaks some test with cage_need_clean engaged.

    @property
    def max_pellet_loaded_engaged(self):
        return self._max_pellet_loaded_engaged

    @max_pellet_loaded_engaged.setter
    def max_pellet_loaded_engaged(self, value):
        prev, self._max_pellet_loaded_engaged = self._max_pellet_loaded_engaged, value
        self._on_property_changed(self.MAX_PELLET_LOADED_ENGAGED, value, prev)
        if value != prev:
            self.post_detector_event(ApiDetectorKind.pelletRefillCountExceeded, value, self._config.use_max_pellet_loaded)
            self.check_state_if_not_detector_thread()

    @property
    def max_consecutive_failed_load_engaged(self):
        return self._max_consecutive_failed_load_engaged

    @max_consecutive_failed_load_engaged.setter
    def max_consecutive_failed_load_engaged(self, value):
        prev, self._max_consecutive_failed_load_engaged = self._max_consecutive_failed_load_engaged, value
        self._on_property_changed(self.MAX_CONSECUTIVE_FAILED_LOAD_ENGAGED, value, prev)
        if value != prev:
            self.post_detector_event(ApiDetectorKind.consecutivePelletLoadFailureExceeded, value,
                                     self._config.use_max_consecutive_failed_load)
            self.check_state_if_not_detector_thread()

    def set_cage_clean_next_day(self, day: date):
        self._cage_clean_next_day = day
        self.check_state()

    @property
    def cage_need_clean_engaged(self):
        return self._cage_need_clean_engaged

    @cage_need_clean_engaged.setter
    def cage_need_clean_engaged(self, value):
        prev, self._cage_need_clean_engaged = self._cage_need_clean_engaged, value
        self._on_property_changed(self.CAGE_NEED_CLEAN_ENGAGED, value, prev)
        if value != prev:
            self.post_detector_event(ApiDetectorKind.cageCleaningRequired, value,
                                     self._config.use_cage_need_clean)
            self.check_state_if_not_detector_thread()

    def _check_cage_need_clean(self):
        cfg = self._config
        check_date = (
            datetime.now()
            + timedelta(hours=cfg.cage_need_clean_look_ahead_hours)
        ).date()
        engaged = check_date >= self._cage_clean_next_day
        if engaged != self._cage_need_clean_engaged:
            logger.notice("Cage need clean: engaged -> %s check_date=%s cage_clean_next_day=%s cfg=%s",
                          engaged, check_date, self._cage_clean_next_day, cfg)
        self.cage_need_clean_engaged = engaged

    def _check_state(self) -> Optional[float]:
        cfg = self._config
        reasons = set()
        #
        self._check_cage_need_clean()
        #
        for reason, use, engaged in (
            (self.MAX_PELLET_LOADED_ENGAGED, cfg.use_max_pellet_loaded, self._max_pellet_loaded_engaged),
            (self.MAX_CONSECUTIVE_FAILED_LOAD_ENGAGED, cfg.use_max_consecutive_failed_load, self._max_consecutive_failed_load_engaged),
            (self.CAGE_NEED_CLEAN_ENGAGED, cfg.use_cage_need_clean, self._cage_need_clean_engaged),
        ):
            if use and engaged:
                reasons.add(reason)
        self._engaged_reasons = reasons
        prev_engaged = self._is_engaged
        new_engaged = len(reasons) > 0
        if not prev_engaged and new_engaged:
            self._logger.notice("Engaging with %s", reasons)
        self.is_engaged = new_engaged

    def update_pellet_loaded(self, loaded: int):
        cfg = self._config
        engaged = loaded >= cfg.max_pellets_loaded_count
        self.max_pellet_loaded_engaged = engaged

    def update_failed_pellet_load(self, *, consecutive: int):
        cfg = self._config
        engaged = consecutive >= cfg.max_consecutive_failed_loaded
        self.max_consecutive_failed_load_engaged = engaged
