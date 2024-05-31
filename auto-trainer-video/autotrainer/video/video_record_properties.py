from enum import Enum


class VideoRecordMode(Enum):
    NONE = 0,
    CONTINUOUS = 1,
    TRIGGER = 2


class VideoRecordProperties:
    def __init__(self, record_mode: VideoRecordMode = VideoRecordMode.NONE, output_location: str = "",
                 interval: int = 3600):
        self.record_mode = record_mode
        self._output_location = output_location
        self._interval = interval

    @property
    def is_record_enabled(self) -> VideoRecordMode:
        return self.record_mode

    @is_record_enabled.setter
    def is_record_enabled(self, value: VideoRecordMode) -> None:
        self.record_mode = value

    @property
    def output_location(self) -> str:
        return self._output_location

    @output_location.setter
    def output_location(self, value: str) -> None:
        self._output_location = value

    @property
    def interval(self) -> int:
        return self._interval
