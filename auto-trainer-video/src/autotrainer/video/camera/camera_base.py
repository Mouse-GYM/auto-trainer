import logging
import time
from typing import Tuple, Optional, ClassVar, Dict, Any

import numpy

logger = logging.getLogger(__name__)


class CameraBase:

    default_params: ClassVar[Dict[str, Any]] = {}

    def __init__(self, name: str = "camera"):
        self._name = name
        self._width = 300
        self._height = 200
        self._fps = 30
        self._is_primary = False
        self._frame_count = 0
        self._capture_start = 0
        self._last_when = 0

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
        self._width = value
        logger.debug(f"<{self._name}> width: {self._width}")

    @property
    def height(self) -> int:
        return self._height

    @height.setter
    def height(self, value: int) -> None:
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

    def init(self) -> None:
        """ Actions that should be taken once after camera creation, but should not happen in the constructor.

        This method will be called after any property changes from the camera url params have been applied.
        """

        pass

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

        self._frame_count += 1

        return None, self._last_when

    def set_property(self, name: str, value: str) -> bool:
        """ Sets known property values, typically from the camera url.

        Subclasses should override to handle custom properties for specific camera types and fallback to calling this
        method for standard properties.

        """

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
            self._is_primary = value.lower() in {"true", "yes", "on", "1"}
        else:
            logger.warning(f"<{self._name}> unknown property {name}")
            return False

        return True

    def _calculate_fps(self) -> float:
        if self._frame_count > 1:
            return self._frame_count * 1e9 / (self._last_when - self._capture_start)

        return 0
