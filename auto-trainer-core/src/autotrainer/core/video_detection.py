import ctypes
import dataclasses
import math
from multiprocessing.sharedctypes import Synchronized

from typing_extensions import Self

from autotrainer.core import ValueHolderDescriptor, get_perf_now, RawValueHolder
from autotrainer.core.configuration.presence_detection_configuration import PresenceDetectionConfig
from autotrainer.core.project.project_info import ProjectInfo
from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.multiproc import get_mp_ctx, EmptyWithContext

logger = get_verbose_logger(__name__)


@dataclasses.dataclass
class PresenceDetectionAttrs:

    pc_threshold = ValueHolderDescriptor()
    # the fg mask sum (as percent vs max(100)) threshold above which the presence is assumed
    _pc_threshold: Synchronized = None

    pc_high_exclude_threshold = ValueHolderDescriptor()
    # but if above this exclude threshold then don't trigger.
    _pc_high_exclude_threshold: Synchronized = None

    mask_lower_zero = ValueHolderDescriptor()
    _mask_lower_zero: Synchronized = None
    # zero all values in the frame below this value

    max_delay_skip_threshold = ValueHolderDescriptor()
    _max_delay_skip_threshold: Synchronized = None
    # remove frames older than this only. all frames within this delay will be taken into account

    # could be todo: allow compare with one frame with the xth previous one (second, or third, for instance),
    #  not only the very next one, that would/could allow detect slower movement/presence

    last_absence_start_perf_c = ValueHolderDescriptor()
    _last_absence_start_perf_c: Synchronized = None

    last_presence_start_perf_c = ValueHolderDescriptor()
    _last_presence_start_perf_c: Synchronized = None

    presence_detected = ValueHolderDescriptor()
    _presence_detected: Synchronized = None

    movement_detected = ValueHolderDescriptor()
    _movement_detected: Synchronized = None

    pc_sum = ValueHolderDescriptor()
    _pc_sum: Synchronized = None

    def __post_init__(self):
        ctx = get_mp_ctx()
        lock = ctx.RLock()
        used = False
        if  self._pc_threshold is None:
            used = True
            self._pc_threshold = ctx.Value(ctypes.c_double, PresenceDetectionConfig.pc_threshold, lock=lock)
        if self._pc_high_exclude_threshold is None:
            used = True
            self._pc_high_exclude_threshold = ctx.Value(ctypes.c_double, PresenceDetectionConfig.pc_high_exclude_threshold, lock=lock)
        if self._mask_lower_zero is None:
            used = True
            self._mask_lower_zero = ctx.Value(ctypes.c_double, PresenceDetectionConfig.mask_lower_zero, lock=lock)
        if self._max_delay_skip_threshold is None:
            used = True
            self._max_delay_skip_threshold = ctx.Value(ctypes.c_double, PresenceDetectionConfig.max_delay_skip_threshold, lock=lock)
        if self._last_absence_start_perf_c is None:
            used = True
            self._last_absence_start_perf_c = ctx.Value(ctypes.c_double, -math.inf, lock=lock)
        if self._last_presence_start_perf_c is None:
            used = True
            self._last_presence_start_perf_c = ctx.Value(ctypes.c_double, -math.inf, lock=lock)
        if self._presence_detected is None:
            used = True
            self._presence_detected = ctx.Value(ctypes.c_bool, False, lock=lock)
        if self._movement_detected is None:
            used = True
            self._movement_detected = ctx.Value(ctypes.c_bool, False, lock=lock)
        if self._pc_sum is None:
            used = True
            self._pc_sum = ctx.Value(ctypes.c_double, 0, lock=lock)
        if not used:
            lock = EmptyWithContext()
        self._lock = lock

    def _loop_over_value_holder_desc(self):
        cls = self.__class__
        return (
            a
            for a in (getattr(cls, k) for k in dir(cls))
            if isinstance(a, ValueHolderDescriptor)
        )

    def __eq__(self, other):
        return all(getattr(self, a.name) == getattr(other, a.name)
                   for a in self._loop_over_value_holder_desc())

    @property
    def lock(self):
        return self._lock

    def to_local_value(self) -> Self:
        """Detach from the shared values"""
        with self._lock:
            dct = {
                f"_{a.name}": RawValueHolder(getattr(self, a.name))
                for a in self._loop_over_value_holder_desc()
            }
        return self.__class__(**dct)

    def to_config(self) -> PresenceDetectionConfig:
        return PresenceDetectionConfig(**{
            field.name: getattr(self, field.name)
            for field in dataclasses.fields(PresenceDetectionConfig)
        })

    def load_config(self, cfg: PresenceDetectionConfig):
        for field in dataclasses.fields(cfg):
            setattr(self, field.name, getattr(cfg, field.name))


