import dataclasses
import math
from collections import namedtuple
from typing import Union, List, Tuple, Dict, Any, Iterable, TypeVar, Type, Optional, Callable
from typing_extensions import Self

import humps
import yaml
from typing_extensions import Self

# NB: import order is very important, put the less specific/most general first, then go in order of dependency.

from .logging import get_verbose_logger

#

logger = get_verbose_logger(__name__)

#

@dataclasses.dataclass
class RawValueHolder:
    value: Any


_no_convert = lambda v: v


class ValueHolderDescriptor:

    def __init__(
        self,
        convert_to: Callable[[Any], Any] = _no_convert,
        convert_from: Callable[[Any], Any] = _no_convert,
    ):
        self._convert_to = convert_to
        self._convert_from = convert_from

    def __set_name__(self, owner, name):
        self.name = name
        self._priv_name = f"_{name}"

    def __get__(self, instance, owner):
        return self._convert_from(getattr(instance, self._priv_name).value)

    def __set__(self, instance, value):
        getattr(instance, self._priv_name).value = self._convert_to(value)

#

def transitions_allow_functions(transitions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Update the dicts to the functions name"""
    for trans in transitions:
        for k in ('trigger', 'before', 'after', 'conditions'):
            v = trans.get(k)
            if isinstance(v, (list, tuple)):
                trans[k] = tuple(
                    sub.__name__ if callable(sub) else sub
                    for sub in v
                )
            elif callable(v):
                trans[k] = v.__name__
    return transitions
#

Pairs3dOffsetT = Union[List[Tuple[str, str]], Tuple[Tuple[str, str], ...]]

_Offset3DTuple = namedtuple("Offset3DTuple", ('x', 'y', 'z'))


class Offset3DTuple(_Offset3DTuple):
    """Named tuple (x, y, z),
    allowing construction with "packed" Offset3DTuple((x, y, z)) or "unpacked" Offset3DTuple(x, y, z) coordinates.
    When "packed": any object having a len() == 3 will be unpacked using python regular:
        x, y, z = args[0]
    Otherwise the construction fails (with anything else in args[0] when len(args) == 1)
    """

    def __new__(cls, *args, **kwargs):
        if len(args) == 1:
            arg0 = args[0]
            if hasattr(arg0, "__len__") and len(arg0) == 3:
                x, y, z = arg0
                return super().__new__(cls, x, y, z, **kwargs)  # noqa
        return super().__new__(cls, *args, **kwargs)  # noqa

    def __repr__(self):
        # to not get "Offset3DTuple(x, y, z)" but instead only "(x, y, z)"
        return str(tuple(self))

    __str__ = __repr__

    def replace(self, x: Optional[float] = None, y: Optional[float] = None, z: Optional[float] = None) -> Self:
        return self.__class__(
            self.x if x is None else x,
            self.y if y is None else y,
            self.z if z is None else z,
        )

    def humanize(self, n_digits: int = 2):
        x, y, z = self
        return f"({x:.0{n_digits}f}, {y:.0{n_digits}f}, {z:.0{n_digits}f})"

    def __pow__(self, other, modulo=None) -> Self:
        if modulo is None:
            return self.__class__(*(v ** other for v in self))
        return self.__class__(
            *(pow(v, other, modulo) for v in self)
        )

    def __rpow__(self, other, modulo=None):
        if modulo is None:
            return self.__class__(*(other ** v for v in self))
        return self.__class__(
            *(pow(other, v, modulo) for v in self)
        )


    def __add__(self, other) -> Self:
        if hasattr(other, "__len__") and len(other) == 3:
            return self.__class__(*(v1 + v2 for v1, v2 in zip(self, other)))
        return self.__class__(*(v + other for v in self))

    __radd__ = __add__

    def __sub__(self, other) -> Self:
        if hasattr(other, "__len__") and len(other) == 3:
            return self.__class__(*(v1 - v2 for v1, v2 in zip(self, other)))
        return self.__class__(*(v - other for v in self))

    def __rsub__(self, other) -> Self:
        if hasattr(other, "__len__") and len(other) == 3:
            return self.__class__(*(v2 - v1 for v1, v2 in zip(self, other)))
        return self.__class__(*(other - v for v in self))

    def __neg__(self) -> Self:
        return self.__class__(-self.x, -self.y, -self.z)

    def __mul__(self, other) -> Self:
        if hasattr(other, "__len__") and len(other) == 3:
            return self.__class__(*(v1 * v2 for v1, v2 in zip(self, other)))
        return self.__class__(*(v * other for v in self))

    __rmul__ = __mul__

    def __truediv__(self, other) -> Self:
        if hasattr(other, "__len__") and len(other) == 3:
            return self.__class__(*(v1 / v2 for v1, v2 in zip(self, other)))
        return self.__class__(*(v / other for v in self))

    def __abs__(self) -> Self:
        return self.__class__(*(abs(v) for v in self))

    @property
    def distance(self) -> float:
        return math.sqrt(sum(c**2 for c in self))

#


def build_kwargs_apply_mapping(
    content: Dict[str, Any],
    mapping: Iterable[Union[str, Tuple[str, str]]],
    *,
    skip_remaining: bool = False,
):
    kwargs = {}
    content = dict(content)  # make copy of 1 level given we'll remove/pop from it
    for cur_map in mapping:
        if isinstance(cur_map, str):
            dest = key = cur_map
        else:
            assert len(cur_map) == 2
            dest, key = cur_map
        if key in content:
            value = content.pop(key)
            if dest not in kwargs:  # first one wins
                kwargs[dest] = value
    # insert whatever remains in content, unless skipped:
    if not skip_remaining:
        kwargs.update(content)
    return kwargs

#


ConfigItemCls = TypeVar("ConfigItemCls")


def make_camelize_representer(section_name: str):

    def representer(dumper: yaml.SafeDumper, obj):
        return dumper.represent_mapping(section_name, {
            humps.camelize(field.name): getattr(obj, field.name)
            for field in dataclasses.fields(obj)
        })

    return representer


def make_decamelize_constructor(cls: Type[ConfigItemCls]):

    # required delayed import for now,
    # not big deal given this function is to be called once only (per config class).
    from .configuration import SystemConfigurationLoader

    def constructor(loader: SystemConfigurationLoader, node: yaml.nodes.MappingNode) -> ConfigItemCls:
        content = loader.construct_mapping(node, deep=True)
        content = humps.decamelize(content)  # decamelize first,
        # "decamelized" names are here after checked against field names
        if loader.safe_load:
            names = [f.name for f in dataclasses.fields(cls)]
            before_count = len(content)
            content = {
                k: v
                for k, v in content.items()
                if k in names
            }
            filtered_count = before_count - len(content)
            if filtered_count != 0:
                logger.verbose("%s: safe load filtered %s unknown properties/attributes",
                               cls.__qualname__, filtered_count)
        return cls(**content)

    return constructor


# MUST come first (but after above definitions):
from .observable_object import ObservableObject, ObservableObjectProtocol

from .analysis import SensorAnalysis, MeasurementData, AudioSpectrumData
from .analysis import LoadCellMonitor, HeadbarPressureMonitor
from .animal import AnimalSubject
from .configuration import SystemConfiguration, BehaviorConfiguration, CameraConfiguration, CameraId, \
    SystemConfigurationLoader
from .configuration import HardwareConfiguration, InferenceConfiguration, PersistenceConfiguration
from .event import EventManager, EventInfo, EventManagerPlugin
from .fixed_array_multiqueue import FixedArrayMultiQueue
from .fixed_array_queue import FixedArrayQueue
from .message import MessageHandler, SystemMessageHandler
from .message import SystemStatusMessageKind, SystemCommandKind, MeasurementMessageProtocol, AudioSpectrumMessage
from .message import MotorConfigurations, Motor
from .perf_monitor import PerfMonitor
from .project import ProjectInfo, ProjectInterval, video_write_ext
from .queue_util import clear_queue
from .notification import NotificationCenter, Notification, TriggerNotification, post_trigger_enable
