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

from autotrainer.core.project import ProjectInfo

logger = logging.getLogger(__name__)


class VideoRecordMode(IntEnum):
    NONE = -1,
    CONTINUOUS = 0,
    TRIGGER = 1


@dataclass
class VideoRecordProperties:
    project_info: ProjectInfo = None
    """Information to determine file names and directories."""
    name: str = "camera"
    """Name used as part of video file names and image capture directory."""
    frame_size: (int, int) = (0, 0)
    """Expected shape of video frames.  Not required for image-only capture."""
    record_mode: VideoRecordMode = VideoRecordMode.CONTINUOUS
    """Continuous or triggered mode for video and image capture. NONE to disabled video recording."""
    fps: int = 30
    """Expected FPS of video feed.  Not required for image-only capture."""
    video_rotate_interval: int = 3600
    """Interval in seconds to rotate the video file.  0 to never rotate."""
    image_interval: int = 0
    """Interval in seconds to capture images.  Values <= 0 disable image capture."""


class VideoRecord(Thread):
    def __init__(self, properties: VideoRecordProperties, input_queue: Queue):
        Thread.__init__(self)

        self._project_info = properties.project_info
        self._name = properties.name
        self._width = properties.frame_size[0]
        self._height = properties.frame_size[1]
        self._fps = properties.fps
        self._record_mode = properties.record_mode
        self._video_rotate_interval = properties.video_rotate_interval
        self._image_interval = properties.image_interval * 1e9

        self._input_queue = input_queue

        self._is_running = True
        self._record_start = None
        self._is_video_enabled = self._record_mode != VideoRecordMode.NONE

        # Windows does not like .mp4 extension when opencv is technically saving to an mkv container.
        self._ext = "mp4" if sys.platform.startswith("linux") else "mkv"

        self._video_writer = None
        self._video_timestamp_file = None

        self._image_location = None
        self._last_image_timestamp = time.perf_counter()

    def run(self) -> None:
        if self._record_mode == VideoRecordMode.CONTINUOUS:
            self._prepare_video_writer()
            self._prepare_image_capture()

        last_when = 0

        while self._is_running:
            try:
                (frame, when) = self._input_queue.get_nowait()

                if frame is None or when is None:
                    # Indicator for trigger disabled
                    self._close_video_writer()
                    self._image_location = None
                    continue

                if self._is_video_enabled:
                    if self._video_writer is None:
                        # If triggered, may not be configured yet for this batch
                        self._prepare_video_writer()

                    if len(numpy.shape(frame)) < 3 or numpy.shape(frame)[2] == 1:
                        self._video_writer.write(numpy.tile(frame[:, :, numpy.newaxis], (1, 1, 3)))
                    else:
                        self._video_writer.write(frame)

                    if self._video_timestamp_file is not None:
                        self._video_timestamp_file.write(f"{when}, {1e9 / (when - last_when)}\n")
                        last_when = when

                if 0 < self._image_interval <= when - self._last_image_timestamp:
                    if self._image_location is None:
                        self._prepare_image_capture()
                    self._last_image_timestamp = when
                    when_str = datetime.fromtimestamp(when / 1e9).strftime("%Y%m%d_%H%M%S_%f")[:-3]
                    cv2.imwrite(os.path.join(self._image_location, self._image_name.format(when=when_str)), frame)
            except Empty:
                time.sleep(0.00001)

            # TODO rotate if is hourly and hour changed, not based on one hour from record start.
            if self._record_start and 0 < self._video_rotate_interval < time.time() - self._record_start:
                self._prepare_video_writer()

        self._close_video_writer()

    def cancel(self):
        self._is_running = False

    def _prepare_image_capture(self):
        if self._project_info is None or not self._project_info.is_valid():
            return

        if self._image_interval > 0 and self._image_location is None:
            path = self._project_info.get_source_path(self._name, self._record_mode != VideoRecordMode.TRIGGER)

            self._image_location = os.path.join(path.location, f"{path.prefix}_images")
            self._image_name = path.prefix + "_{when}" + ".png"

            path = Path(self._image_location)
            path.mkdir(parents=True, exist_ok=True)

            logger.debug(f"<{self.name}> image capture to: {self._image_location}")

    def _prepare_video_writer(self):
        self._close_video_writer()

        if self._project_info is None or not self._project_info.is_valid():
            return

        if not self._is_video_enabled:
            return

        self._record_start = time.time()

        is_hourly = self._record_mode != VideoRecordMode.TRIGGER

        video_path = self._project_info.get_source_path(self._name, is_hourly)

        path = Path(video_path.location)
        path.mkdir(parents=True, exist_ok=True)

        location = f"{video_path.full_path}.{self._ext}"

        index = 0

        while os.path.exists(location):
            index += 1
            location = f"{video_path.full_path}_{index}.{self._ext}"

        logger.debug(f"<{self.name}> using next video file: {location}")

        ts_file = self._project_info.get_video_timestamp_file(self._name, is_hourly,
                                                              "" if index == 0 else "_" + str(index))

        self._video_timestamp_file = open(ts_file, "a")

        self._video_writer = cv2.VideoWriter(location, cv2.VideoWriter_fourcc(*'mp4v'), self._fps,
                                             (self._width, self._height))

    def _close_video_writer(self):
        if self._video_writer is not None:
            self._video_writer.release()
            self._video_writer = None
            if self._record_mode == VideoRecordMode.TRIGGER:
                self._project_info.current_session += 1

        if self._video_timestamp_file is not None:
            self._video_timestamp_file.close()
            self._video_timestamp_file = None
