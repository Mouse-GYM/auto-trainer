import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from pathlib import Path
from queue import Queue, Empty
from threading import Thread

import cv2
import numpy

logger = logging.getLogger(__name__)


class VideoRecordMode(IntEnum):
    NONE = -1,
    CONTINUOUS = 0,
    TRIGGER = 1


@dataclass
class VideoRecordProperties:
    base_output_location: str = ""
    name: str = "camera"
    size: (int, int) = (0, 0)
    fps: int = 30
    record_mode: VideoRecordMode = VideoRecordMode.CONTINUOUS
    rotate_interval: int = 3600
    image_interval: int = 0


class VideoRecord(Thread):
    def __init__(self, properties: VideoRecordProperties, input_queue: Queue):
        Thread.__init__(self)

        self._output_location = properties.base_output_location
        self._name = properties.name
        self._rotate_interval = properties.rotate_interval
        self._width = properties.size[0]
        self._height = properties.size[1]
        self._fps = properties.fps
        self._image_interval = properties.image_interval * 1e9
        self._image_location = None
        self._input_queue = input_queue

        self._is_running = True
        self._record_start = None

        self._ext = "mp4" if sys.platform.startswith("linux") else "mkv"

        self._writer = None
        self._timestamp = None

        self._when_last_still_image = time.perf_counter()

    def run(self) -> None:
        last_when = 0

        while self._is_running:
            try:
                (frame, when) = self._input_queue.get_nowait()

                if frame is None or when is None:
                    continue

                if self._writer is None:
                    self._update_writer()

                if self._writer is None:
                    continue

                if len(numpy.shape(frame)) < 3 or numpy.shape(frame)[2] == 1:
                    self._writer.write(numpy.tile(frame[:, :, numpy.newaxis], (1, 1, 3)))
                else:
                    self._writer.write(frame)

                if 0 < self._image_interval <= when - self._when_last_still_image:
                    self._when_last_still_image = when
                    cv2.imwrite(os.path.join(self._image_location, f"{when}.png"), frame)

                if self._timestamp is not None:
                    self._timestamp.write(f"{when}, {1e9 / (when - last_when)}\n")
                    last_when = when
            except Empty:
                time.sleep(0.0001)

            if self._writer is not None and time.time() - self._record_start > self._rotate_interval:
                self._update_writer()

        self._close_writer()

    def cancel(self):
        self._is_running = False

    def _close_writer(self):
        if self._writer is not None:
            self._writer.release()
            self._writer = None
        if self._timestamp is not None:
            self._timestamp.close()
            self._timestamp = None

    def _update_writer(self):
        self._close_writer()

        if self._output_location is None:
            return

        if self._image_interval > 0 and self._image_location is None:
            self._image_location = os.path.join(f"{Path(self._output_location).parent}", f"{self._name}_still")
            path = Path(self._image_location)
            path.mkdir(parents=True, exist_ok=True)

        self._record_start = time.time()

        file_timestamp = datetime.now()

        location = self._output_location + f"_{file_timestamp.strftime('%H%M%S')}_{self._name}.{self._ext}"

        logger.debug(f"<{self.name}> using next output file: {location}")

        self._timestamp = open(
            self._output_location + f"_{file_timestamp.strftime('%H%M%S')}_{self._name}_timestamps.txt", "w")

        self._writer = cv2.VideoWriter(location, cv2.VideoWriter_fourcc(*'mp4v'), self._fps,
                                       (self._width, self._height))
