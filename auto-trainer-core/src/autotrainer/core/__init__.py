import math
from collections import namedtuple
from typing import Union, List, Tuple

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

    def __add__(self, other):
        if hasattr(other, "__len__") and len(other) == 3:
            return self.__class__(*(v1 + v2 for v1, v2 in zip(self, other)))
        return super().__add__(other)

    __radd__ = __add__

    def __sub__(self, other):
        if hasattr(other, "__len__") and len(other) == 3:
            return self.__class__(*(v1 - v2 for v1, v2 in zip(self, other)))
        raise TypeError(f"Cannot sub object of type {type(other)}")

    def __rsub__(self, other):
        if hasattr(other, "__len__") and len(other) == 3:
            return self.__class__(*(v2 - v1 for v1, v2 in zip(self, other)))
        raise TypeError(f"Cannot sub object of type {type(other)}")

    def __neg__(self):
        return self.__class__(-self.x, -self.y, -self.z)

    @property
    def distance(self) -> float:
        return math.sqrt(sum(c**2 for c in self))


#

from .analysis import SensorAnalysis, MeasurementData, AudioSpectrumData
from .analysis import LoadCellMonitor, HeadbarPressureMonitor
from .animal import AnimalSubject
from .configuration import SystemConfiguration, BehaviorConfiguration, CameraConfiguration, CameraId
from .configuration import HardwareConfiguration, InferenceConfiguration, PersistenceConfiguration
from .configuration import get_system_configuration_dumper
from .event import EventManager, EventInfo, EventManagerPlugin
from .fixed_array_multiqueue import FixedArrayMultiQueue
from .fixed_array_queue import FixedArrayQueue
from .message import MessageHandler, SystemMessageHandler
from .message import SystemStatusMessageKind, SystemCommandKind, MeasurementMessage, AudioSpectrumMessage
from .message import MotorConfigurations, Motor
from .observable_object import ObservableObject, ObservableObjectProtocol
from .perf_monitor import PerfMonitor
from .project import ProjectInfo, ProjectInterval, video_write_ext
from .queue_util import clear_queue, trim_queue
from .notification import NotificationCenter, Notification, TriggerNotification, post_trigger_enable
