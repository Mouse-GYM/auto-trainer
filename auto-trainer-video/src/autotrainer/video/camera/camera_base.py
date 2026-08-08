import dataclasses
import logging
import math
import time
from typing import Tuple, Optional, ClassVar, Dict, Any, Callable

import numpy

from autotrainer.core import get_perf_now

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class CameraBaseDefaultParams:

    width: int = 300
    height: int = 200
    fps: float = 30


class CameraBase:

    class ParamsType:
        """Allows Camera subclasses to define the type of their specific possible parameters"""
        name = str
        width = int
        height = int
        fps = float

    default_params: ClassVar[Dict[str, Any]] = dataclasses.asdict(CameraBaseDefaultParams())
    # possible default "params" for camera class,
    # must use same keys than in config file.
    # Is used to pre-set/applied on the camera instance, once it's created,
    # but before any eventual custom params from config file, that can so override them.

    SETTABLE_PROPERTIES = frozenset((
        "ignore_pose_borders",
        "ignore_pose_corners",
        "ignore_pose_replace_value",
        "ignore_pose_show_in_video_stream",
        "ignore_pose_show_in_video_stream_replace_value",
    ))

    # defined as class attrs (for default value), but can be set with different value on the camera instance,
    # using a camera parameter with the same name:
    _ignore_pose_borders = (0, 0, 0, 0)  # top,      left,      right,       bottom
    _ignore_pose_corners = (0, 0, 0, 0)  # top-left, top-right, bottom-left, bottom-right
    _ignore_pose_replace_value = 0
    _ignore_pose_show_in_video_stream = True
    _ignore_pose_show_in_video_stream_replace_value = 255
    # not included in CameraBaseDefaultParams on purpose, to not pollute config with the default value.

    def __init__(self, name: str = "camera"):
        self._name = name
        self._width = 0
        self._height = 0
        self._fps = 0
        self._is_primary = False
        self._frame_count = 0
        self._capture_start = 0
        self._last_when = 0
        self._last_frame_id = -1
        self._last_frame_perf_c = -math.inf
        self._last_frame_time = -math.inf
        self._refresh_watchdog: Optional[Callable[[], None]] = None
        self._prev_watchdog_refresh = -math.inf

    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, value: int) -> None:
        self._name = value

    @property
    def width(self) -> int:
        return self._width

    @width.setter
    def width(self, value: int) -> None:
        if __debug__:
            if not isinstance(value, int):
                logger.warning("Received non-int type value for width: %s: %r", type(value), value)
        self._width = value
        logger.debug(f"<{self._name}> width: {self._width}")

    @property
    def height(self) -> int:
        return self._height

    @height.setter
    def height(self, value: int) -> None:
        if __debug__:
            if not isinstance(value, int):
                logger.warning("Received non-int type value for height: %s: %r", type(value), value)
        self._height = value
        logger.debug(f"<{self._name}> height: {self._height}")

    @property
    def fps(self) -> int:
        return self._fps

    @fps.setter
    def fps(self, value: int) -> None:
        self._fps = value
        logger.debug(f"<{self._name}> fps: {self._fps}")

    @property
    def is_primary(self) -> bool:
        return self._is_primary

    @property
    def frame_id(self) -> int:
        """Returns the last frame id (frame counter)"""
        return self._last_frame_id
    
    @property
    def frame_perf_c(self) -> float:
        """Returns the last frame system perf_counter, as precise as possible"""
        return self._last_frame_perf_c

    @property
    def frame_unix_time(self) -> float:
        return self._last_frame_time

    def init(self) -> None:
        """ Actions that should be taken once after camera creation, but should not happen in the constructor.

        This method will be called after any property changes from the camera url params have been applied.
        """

    def prepare_capture(self) -> None:
        """ Should be called once before capturing frames.

        Subclasses must call this method when overriding to reset frame count.
        """
        self._last_when = 0
        self._frame_count = 0

    def end_capture(self) -> None:
        """ Should be called once after capturing frames."""

        logger.debug(f"<{self._name}> approximate fps: ~{self._calculate_fps():.1f}")

    def capture(self) -> Tuple[Optional[numpy.ndarray], int]:
        """ Called repeatedly to capture the next frame

        Subclasses must call this method when overriding or take responsibility for increasing frame count and tracking
        performance times (capture start and last frame time).

        :returns: tuple containing a numpy array with shape (height, width) and an associated timestamp in nanoseconds
        :rtype: (numpy.ndarray, int)
        """

        if self._frame_count == 0:
            self._last_when = self._capture_start = time.time_ns()

        self._last_when = time.time_ns()
        self._last_frame_perf_c = get_perf_now()
        self._last_frame_time = time.time()

        self._frame_count += 1
        self._last_frame_id += 1

        return None, self._last_when

    def set_property(self, name: str, value: Any) -> bool:
        """ Sets known property values, typically from the camera url.

        Subclasses should override to handle custom properties for specific camera types and fallback to calling this
        method for standard properties.
        """
        # nb: since VideoManager now is doing the full decoding of the camera properties,
        # then all the "decode/parsing" applied here is normally not anymore necessary.

        name = name.lower()

        if name == "width":
            self.width = int(value)
        elif name == "height":
            self.height = int(value)
        elif name == "fps":
            self.fps = int(value)
        elif name == "name":
            self.name = value
        elif name == "primary":
            self._is_primary = value.lower() in {"true", "yes", "on", "1"} if isinstance(value, str) else bool(value)
        elif name in self.SETTABLE_PROPERTIES:
            setattr(self, name, value)
        else:
            logger.warning(f"<{self._name}> unknown property {name}")
            return False

        return True

    def _calculate_fps(self) -> float:
        if self._frame_count > 1:
            return self._frame_count * 1e9 / (self._last_when - self._capture_start)

        return 0

    def set_refresh_watchdog(self, func: Optional[Callable[[], None]]) -> None:
        """Set the desired optional watchdog refresh func"""
        self._refresh_watchdog = func

    def refresh_watchdog(self):
        """Shall be called, frequently enough, by any implementation desiring to keep a possible watchdog alive
        while a long capture is in progress"""
        func = self._refresh_watchdog
        p_now = time.perf_counter()
        if func is not None:
            # still prevent too "frequent" refresh
            if p_now - self._prev_watchdog_refresh >= 0.5:
                func: Callable
                func()
                self._prev_watchdog_refresh = p_now

    #

    @property
    def ignore_pose_borders(self) -> Tuple[int, int, int, int]:
        return self._ignore_pose_borders

    @ignore_pose_borders.setter
    def ignore_pose_borders(self, value: Tuple[int, int, int, int]):
        if (
            not isinstance(value, (list, tuple))
            or len(value) != 4
            or any(not isinstance(v, int) or v < 0 for v in value)
        ):
            logger.warning("%s: skipping invalid ignore_pose_borders: %s", self._name, value)
            return
        self._ignore_pose_borders = value

    @property
    def ignore_pose_corners(self) -> Tuple[int, int, int, int]:
        return self._ignore_pose_corners

    @ignore_pose_corners.setter
    def ignore_pose_corners(self, value: Tuple[int, int, int, int]):
        if (
            not isinstance(value, (list, tuple))
            or len(value) != 4
            or any(not isinstance(v, int) or v < 0 for v in value)
        ):
            logger.warning("%s: skipping invalid ignore_pose_corners: %s", self._name, value)
            return
        self._ignore_pose_corners = value

    @property
    def ignore_pose_replace_value(self):
        return self._ignore_pose_replace_value

    @ignore_pose_replace_value.setter
    def ignore_pose_replace_value(self, value: int):
        if not isinstance(value, int) or not 0 <= value <= 255:
            logger.warning("%s: skipping invalid ignore_pose_replace_value: %s", self._name, value)
            return
        self._ignore_pose_replace_value = value

    @property
    def ignore_pose_show_in_video_stream(self):
        return self._ignore_pose_show_in_video_stream

    @ignore_pose_show_in_video_stream.setter
    def ignore_pose_show_in_video_stream(self, value):
        self._ignore_pose_show_in_video_stream = value

    @property
    def ignore_pose_show_in_video_stream_replace_value(self):
        return self._ignore_pose_show_in_video_stream_replace_value

    @ignore_pose_show_in_video_stream_replace_value.setter
    def ignore_pose_show_in_video_stream_replace_value(self, value):
        if not isinstance(value, int) or not 0 <= value <= 255:
            logger.warning("%s: skipping invalid ignore_pose_show_in_video_stream_replace_value: %s", self._name, value)
            return
        self._ignore_pose_show_in_video_stream_replace_value = value
