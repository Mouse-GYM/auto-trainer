from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from queue import Queue, Empty
from threading import Thread

import cv2
import numpy

from autotrainer.core import trim_queue
from autotrainer.core import ProjectInfo, ProjectInterval
from autotrainer.core.logging import get_verbose_logger

logger = get_verbose_logger(__name__)


class VideoRecordMode(IntEnum):
    NONE = -1
    CONTINUOUS = 0
    TRIGGER = 1


@dataclass
class VideoRecordProperties:
    project_info: ProjectInfo | None = None
    """Information to determine file names and directories."""
    name: str = "camera"
    """Name used as part of video file names and image capture directory."""
    frame_size: (int, int) = (0, 0)
    """Expected shape of video frames.  Not required for image-only capture."""
    fps: int = 30
    """Expected FPS of video feed.  Not required for image-only capture."""
    record_mode: VideoRecordMode = VideoRecordMode.NONE
    """Continuous or triggered mode for video and image capture. NONE to disabled video recording."""
    video_rotate_interval: int = -1
    """Interval in seconds to rotate the video file.  0 to never rotate. Negative to disabled video recording."""
    image_interval: int = 0
    """Interval in seconds to capture images.  Values <= 0 disable image capture."""
    queue_batch_size = 60
    """Number of frames to batch for passing between capture and record queues."""

    def should_record(self, is_triggered: bool) -> bool:
        any_active = self.project_info is not None and (self.video_rotate_interval >= 0 or self.image_interval > 0)

        if self.record_mode == VideoRecordMode.CONTINUOUS:
            return any_active
        elif self.record_mode == VideoRecordMode.TRIGGER:
            return is_triggered and any_active

        return False


class VideoRecord(Thread):
    def __init__(self, properties: VideoRecordProperties, input_queue: Queue):
        Thread.__init__(self, name=properties.name)
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

        self._is_video_enabled = self._video_rotate_interval >= 0
        self._video_writer = None
        self._video_timestamp_file = None

        self._image_location: str
        self._last_image_timestamp = time.perf_counter()

        self._interval_mode = ProjectInterval.NONE
        self._interval_reference = -1

    def run(self):
        logger.notice("%s: running", self)
        try:
            self._run()
        except Exception as err:
            logger.exception("%s: Error during run: %s", err)

    def _run(self) -> None:
        if self._project_info is None or not self._project_info.is_valid():
            logger.error("video recording and image capture can not proceed without value project information")
            return

        if self._record_mode == VideoRecordMode.CONTINUOUS:
            self._interval_mode = ProjectInterval.HOUR
            self._prepare_writers()

        last_when = 0
        check_count = 0

        while self._is_running:
            try:
                queue_list = self._input_queue.get(timeout=1)
            except Empty:
                continue

            try:
                # if frame is None or when is None:
                if len(queue_list) == 0:
                    # Indicator for trigger disabled
                    self._close_writers()
                    continue

                for frame, when in queue_list:
                    if self._is_video_enabled:
                        if self._video_writer is None:
                            # If triggered, may not be configured yet for this batch
                            self._prepare_writers()

                        if len(numpy.shape(frame)) < 3 or numpy.shape(frame)[2] == 1:
                            self._video_writer.write(numpy.tile(frame[:, :, numpy.newaxis], (1, 1, 3)))
                        else:
                            self._video_writer.write(frame)

                        if self._video_timestamp_file is not None:
                            self._video_timestamp_file.write(f"{when}, {1e9 / (when - last_when)}\n")
                            last_when = when

                    if 0 < self._image_interval <= when - self._last_image_timestamp:
                        if self._image_location is None:
                            self._prepare_writers()
                        self._last_image_timestamp = when
                        when_str = datetime.fromtimestamp(when / 1e9).strftime("%Y%m%d_%H%M%S_%f")[:-3]
                        assert isinstance(self._image_location, str)
                        cv2.imwrite(os.path.join(self._image_location, self._image_name.format(when=when_str)), frame)

                    check_count += 1

                    if check_count > self._fps:
                        if trim_queue(self._input_queue, 5):
                            logger.debug(f"<{self.name}>: queue trimmed")
                        check_count = 0
                        self._check_writers()

            except Exception as err:
                logger.exception("%s: loop error: %s", self, err)

            try:
                self._check_writers()
            except Exception as err:
                logger.exception("%s: check writers error: %s", self, err)

        logger.notice("%s: main loop exited", self)
        self._close_writers()

    def cancel(self):
        self._is_running = False

    def _check_writers(self):
        if self._interval_mode != ProjectInterval.NONE:
            timestamp = datetime.now()

            needs_update = timestamp.hour != self._interval_reference \
                if self._interval_mode == ProjectInterval.HOUR \
                else timestamp.minute != self._interval_reference

            if needs_update:
                self._prepare_writers()

    def _prepare_writers(self):
        logger.info("%s: preparing writers...", self)
        self._interval_reference = self._project_info.get_interval(self._interval_mode)
        self._prepare_video_writer()
        self._prepare_image_capture()

    def _close_writers(self):
        logger.info("%s: closing writers...", self)
        self._close_image_writer()
        self._close_video_writer()

    def _prepare_image_capture(self):
        self._close_image_writer()
        if self._image_interval > 0:
            self._image_location, self._image_name = (
                self._project_info.get_image_capture_path(self._name, interval=self._interval_mode))
            logger.debug(f"<{self.name}>: image capture to {self._image_location}")

    def _close_image_writer(self):
        self._image_location = None

    def _prepare_video_writer(self):
        self._close_video_writer()

        if not self._is_video_enabled:
            logger.warning("_prepare_video_writer but _is_video_enabled False")
            return

        self._record_start = time.time()

        video_file, timestamp_file, _ = self._project_info.get_video_path(
            self._name, interval=self._interval_mode, allow_overwrite=True)

        logger.notice(f"<{self.name}>: video record to {video_file}")

        self._video_writer = cv2.VideoWriter(video_file, cv2.VideoWriter_fourcc(*'mp4v'), self._fps,
                                             (self._width, self._height))
        self._video_timestamp_file = open(timestamp_file, "a")

    def _close_video_writer(self):
        if self._video_writer is not None:
            self._video_writer.release()
            self._video_writer = None

        if self._video_timestamp_file is not None:
            self._video_timestamp_file.close()
            self._video_timestamp_file = None
