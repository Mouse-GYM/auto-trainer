import ctypes
import dataclasses
import math
from multiprocessing.sharedctypes import Synchronized
from typing import Optional

from typing_extensions import Self

from autotrainer.core import ValueHolderDescriptor, RawValueHolder
from autotrainer.core.configuration.presence_detection_configuration import PresenceDetectionConfig
from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.multiproc import get_mp_ctx, EmptyWithContext

logger = get_verbose_logger(__name__)


@dataclasses.dataclass
class PresenceDetectionAttrs:

    pc_threshold = ValueHolderDescriptor[float]()
    # the fg mask sum (as percent vs max(100)) threshold above which the presence is assumed
    _pc_threshold: Optional[Synchronized] = None

    pc_high_exclude_threshold = ValueHolderDescriptor[float]()
    # but if above this exclude threshold then don't trigger.
    _pc_high_exclude_threshold: Optional[Synchronized] = None

    mask_lower_zero = ValueHolderDescriptor[float]()
    _mask_lower_zero: Optional[Synchronized] = None
    # zero all values in the frame below this value

    max_delay_skip_threshold = ValueHolderDescriptor[float]()
    _max_delay_skip_threshold: Optional[Synchronized] = None
    # remove frames older than this only. all frames within this delay will be taken into account

    # could be todo: allow compare with one frame with the xth previous one (second, or third, for instance),
    #  not only the very next one, that would/could allow detect slower movement/presence

    last_absence_start_perf_c = ValueHolderDescriptor[float]()
    _last_absence_start_perf_c: Optional[Synchronized] = None

    last_presence_start_perf_c = ValueHolderDescriptor[float]()
    _last_presence_start_perf_c: Optional[Synchronized] = None

    presence_detected = ValueHolderDescriptor[bool]()
    _presence_detected: Optional[Synchronized] = None

    movement_detected = ValueHolderDescriptor[bool]()
    _movement_detected: Optional[Synchronized] = None

    pc_sum = ValueHolderDescriptor[float]()
    _pc_sum: Optional[Synchronized] = None

    def __post_init__(self):
        used = False
        prep_shared = []
        def make_shared(attr, *args, **kwargs):
            nonlocal used
            dst_attr = f"_{attr}"
            if getattr(self, dst_attr) is not None:
                return
            used = True
            prep_shared.append((dst_attr, lambda lck: ctx.Value(*args, **kwargs, lock=lck)))

        make_shared("pc_threshold", ctypes.c_double, PresenceDetectionConfig.pc_threshold)
        make_shared("pc_high_exclude_threshold", ctypes.c_double, PresenceDetectionConfig.pc_high_exclude_threshold)
        make_shared("mask_lower_zero", ctypes.c_double, PresenceDetectionConfig.mask_lower_zero)
        make_shared("max_delay_skip_threshold", ctypes.c_double, PresenceDetectionConfig.max_delay_skip_threshold)
        make_shared("last_absence_start_perf_c", ctypes.c_double, -math.inf)
        make_shared("last_presence_start_perf_c", ctypes.c_double, -math.inf)
        make_shared("presence_detected", ctypes.c_bool, False)
        make_shared("movement_detected", ctypes.c_bool, False)
        make_shared("pc_sum", ctypes.c_double, 0)

        if not used:
            lock = EmptyWithContext()
        else:
            logger.verbose("creating lock for internal shared values: %s",
                           tuple(attr for attr, _ in prep_shared))
            ctx = get_mp_ctx()
            lock = ctx.RLock()
            for attr, func in prep_shared:
                setattr(self, attr, func(lck=lock))
        self._lock = lock

    def __eq__(self, other):
        return all(getattr(self, a) == getattr(other, a)
                   for a in (a.name.lstrip("_") for a in dataclasses.fields(self)))

    @property
    def lock(self):
        return self._lock

    def to_local_value(self) -> Self:
        """Detach from the shared values ; given this is used with lock, this ensures consistency for the caller/user"""
        with self._lock:
            dct = {
                f"_{a}": RawValueHolder(getattr(self, a))
                for a in (a.name.lstrip("_") for a in dataclasses.fields(self))
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
