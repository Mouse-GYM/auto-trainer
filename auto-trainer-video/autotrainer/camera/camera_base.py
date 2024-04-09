import logging

import numpy

logger = logging.getLogger(__name__)


class CameraBase:
    def __init__(self, name: str = "camera"):
        self._name = name
        self._width = 300
        self._height = 200
        self._fps = 30
        self._is_primary = False

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
    def fps(self) -> float:
        return self._fps

    @fps.setter
    def fps(self, value: float) -> None:
        self._fps = value
        logger.debug(f"<{self._name}> fps: {self._fps}")

    @property
    def is_primary(self) -> bool:
        return self._is_primary

    def init(self) -> None:
        pass

    def prepare_capture(self) -> None:
        pass

    def end_capture(self) -> None:
        pass

    def capture(self) -> numpy.ndarray:
        pass

    def set_property(self, name: str, value: str) -> bool:
        if name == "width":
            self.width = int(value)
        elif name == "height":
            self.height = int(value)
        elif name == "fps":
            self.fps = int(value)
        elif name == "name":
            self.name = value
        else:
            return False

        return True
