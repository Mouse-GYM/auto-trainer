from __future__ import annotations

import logging
import multiprocessing
import queue
import time
import os
from dataclasses import dataclass
from queue import Queue
from enum import Enum, IntEnum
from multiprocessing import Process, Value, Array
from typing import Callable, Dict, Union, Optional, List

import numpy
import verboselogs

from autotrainer.core import FixedArrayMultiQueue, FixedArrayQueue, ProjectInfo
from autotrainer.core.logging import get_verbose_logger, set_logger_level
from autotrainer.core.fixed_array_queue import BufferResult
from autotrainer.core.message import FrameIndexCategory
from .detection import PresenceDetectionAttrs, VideoDetection

from .video_manager import VideoManager
from .video_record import VideoRecord, VideoRecordProperties, VideoRecordMode

logger = get_verbose_logger(__name__)


class CaptureCommandKind(Enum):
    """Commands accepted by VideoCaptureProcess through the command Queue"""
    TERMINATE = 1
    """Fully terminate the Process"""

    ENABLE_CAPTURE = 2
    """Enable image capture"""

    DISABLE_CAPTURE = 3
    """Disable image capture"""

    ENABLE_RECORDING = 4
    """Enable image recording (requires capture enabled)"""

    DISABLE_RECORDING = 5
    """Disable image recording"""

    SET_LOGGER_LEVEL = 6
    """Set a logger log level"""


class CaptureProcessStatus(IntEnum):
    """ Valid VideoCaptureProcess states available through the status Value"""
    FAILED = -1
    """Failed to configure or run process"""
    UNKNOWN = 0,
    """Uninitialized value not yet set by capture process"""
    INITIALIZED = 1
    """The process is created, but not started"""
    RUNNING = 2
    """The process is running the capture loop"""
    TERMINATED = 3
    """The capture loop is terminated"""


@dataclass
class CaptureCameraAttrs:
    """
    Camera attributes for VideoCapture configuration

    Attributes
    ----------
    name: str
        the name to use for the Process and in log messages
    url: str
        the camera URL for the capture process
    """
    name: str
    url: str


@dataclass
class CaptureInferenceAttrs:
    """
    Inference attributes for VideoCapture configuration

    Attributes
    ----------
    queue: Queue
        A queue to push frames for pellet
    index: int
        The index of this camera in the queue
    """
    queue: Optional[FixedArrayMultiQueue]  # Union[Queue, FixedArrayMultiQueue]
    index: int


@dataclass
class CaptureAttrs:
    """
    Attributes for VideoCapture configuration
    """
    command_queue: multiprocessing.Queue
    """Input queue for submitting commands to the capture process"""

    status: Value
    """Flag for status of the capture process - value is read-only to callers"""

    image_queue: Optional[Union[Queue, FixedArrayQueue]]
    """Queue for camera frame output"""

    frame: Value
    """Current frame index - value is read-only to callers"""

    camera: CaptureCameraAttrs
    """Camera attributes for the capture process"""

    errors: Array
    """Multiprocessing Array for communicating errors - value is read-only to callers"""

    inference: Optional[CaptureInferenceAttrs] = None
    """Inference attributes for the capture process (optional)"""

    fps_image_queue: Optional[float] = 15
    """Desired write FPS for the image_queue, if None then default to capture FPS"""

    presence_detection_attrs: Optional[PresenceDetectionAttrs] = None
    """Optional Presence detection"""


class VideoCapture(Process):
    """
    Process-based class for video capture and recording.

    VideoCapture runs as a separate process for video capture and recording.  An optional image queue can be provided
    to receive frames from the camera.  A separate, optional pellet queue can be provided to feed pellet models
    or any other process.
    """

    def __init__(
        self,
        attrs: CaptureAttrs,
        record_properties: Optional[VideoRecordProperties] = None,
        project_info: Optional[ProjectInfo] = None,
    ):
        super().__init__(name=attrs.camera.name)

        self._name = attrs.camera.name
        self._camera_url = attrs.camera.url

        self._project_info = project_info
        self._command_queue = attrs.command_queue
        self._status = attrs.status
        self._image_queue: Optional[Union[Queue, FixedArrayQueue]] = attrs.image_queue
        self._image_queue_frame_delay = None if attrs.fps_image_queue is None else 1 / attrs.fps_image_queue
        self._network_queue: Optional[FixedArrayMultiQueue]

        if attrs.inference is not None:
            self._network_queue = attrs.inference.queue
            self._camera_idx = attrs.inference.index
        else:
            self._network_queue = None
            self._camera_idx = -1

        self._is_record_active = False

        if record_properties is not None:
            self._record_properties = record_properties
            self._is_record_active = record_properties.should_record(False)
            self._record_batch_size = record_properties.queue_batch_size
        else:
            self._record_properties = VideoRecordProperties(record_mode=VideoRecordMode.NONE)
            self._record_batch_size = 30

        self._errors = attrs.errors

        self._is_running = True
        self._is_capturing = False
        self._camera = None
        self._record = None
        self._record_queue: Optional[Queue] = None
        self._record_queue_list: List = []

        self._detection_attrs = attrs.presence_detection_attrs

        self.command_handler: Dict[CaptureCommandKind, Callable[[object], None]] = {
            CaptureCommandKind.TERMINATE: self._user_terminate,
            CaptureCommandKind.ENABLE_CAPTURE: self._begin_capture,
            CaptureCommandKind.DISABLE_CAPTURE: self._end_capture,
            CaptureCommandKind.ENABLE_RECORDING: self._enable_trigger,
            CaptureCommandKind.DISABLE_RECORDING: self._disable_trigger,
            CaptureCommandKind.SET_LOGGER_LEVEL: set_logger_level,
        }

        self._set_status(CaptureProcessStatus.INITIALIZED)

    def run(self):
        from autotrainer.core.logging import setup_logging
        log_level = os.getenv("VIDEO_CAPTURE_LOG_LEVEL", verboselogs.VERBOSE)
        if isinstance(log_level, str) and log_level.isdigit():
            log_level = int(log_level)
        setup_logging(root_level=log_level)

        logger.info("%s: started running", self)

        if not self._prepare_to_run():
            return

        self._run_capture_loop()
        self._terminate_capture_loop()

    def _set_status(self, status: CaptureProcessStatus):
        self._status.value = status

    def _set_error(self, error: Exception):
        self._set_status(CaptureProcessStatus.FAILED)
        if self._errors:
            self._errors.value = f"{error}"[:len(self._errors)].encode()

    def _prepare_to_run(self) -> bool:
        logger.info(f"<{self._name}> process started: %s", self._network_queue)
        try:
            if self._camera_url is None:
                logger.error(f"<{self._name}> camera url not specified")
                return False

            VideoManager.open()

            self._create_camera()
            self._camera.prepare_capture()

            self._record_queue = Queue()
            self._record_properties.name = self._name
            self._record_properties.frame_size = (self._camera.width, self._camera.height)
            self._record_properties.fps = self._camera.fps

            self._record = VideoRecord(self._record_properties, self._record_queue)
            self._record.start()

            if self._detection_attrs is None or self._project_info is None:
                self._video_detection = None
            else:
                self._video_detection = VideoDetection(self._project_info, self._detection_attrs)
                self._video_detection.start()

            logger.verbose("%s: video_detection: %s", self._name, self._video_detection)
            self._set_status(CaptureProcessStatus.RUNNING)

            return True
        except Exception as err:
            logger.exception("%s: Error during prepare to run: %s", self, err)
            self._set_error(err)
            return False

    def _run_capture_loop(self) -> None:
        fault_count = 0
        cnt_net_q_put = 0
        cur_frame_idx = -1
        record_start_frame_idx = None
        next_t_image_q = time.time()
        next_t_cmd_q = next_t_image_q
        img_q = self._image_queue
        rec_q_list = self._record_queue_list
        rec_q = self._record_queue
        capture = self._camera.capture
        net_q_put = None if self._network_queue is None else self._network_queue.put
        image_queue_delay = self._image_queue_frame_delay
        get_command = None if self._command_queue is None else self._command_queue.get_nowait
        empty_frame = numpy.zeros(self._record_properties.frame_size, dtype=numpy.uint8)
        vid_detection = self._video_detection
        logger.notice("%s: starting capture loop ..", self)
        while self._is_running:
            t_now = time.time()
            try:
                if get_command is not None and t_now > next_t_cmd_q:
                    while True:
                        cmd = None
                        try:
                            cmd, context = get_command()
                            self._handle_command(cmd, context)
                        except queue.Empty:
                            break
                        except Exception as err:
                            logger.exception("Failure executing cmd %s: %s", cmd, err)
                    next_t_cmd_q += 0.005
                    rec_q_list = self._record_queue_list

                if not self._is_capturing:
                    time.sleep(0.001)
                    record_start_frame_idx = None
                    rec_q_list = self._record_queue_list = []
                    continue

                frame, when = capture()
                cur_frame_idx += 1

                if img_q is not None:
                    # image queue goes to GUI video reader frame, currently FixedArrayQueue
                    if t_now >= next_t_image_q:
                        if image_queue_delay is not None:
                            next_t_image_q = t_now + image_queue_delay
                        if len(numpy.shape(frame)) < 3:
                            img_q.put(frame)
                        else:
                            img_q.put(frame[:, :, 0])

                if vid_detection is not None:
                    vid_detection.update_frame(when, frame)

                if self._is_record_active:
                    # record queue goes to video save to disk/file
                    if record_start_frame_idx is None:
                        logger.notice("Starting record with frame %s", cur_frame_idx)
                        record_start_frame_idx = cur_frame_idx
                        rec_q.put([(frame, when)])  # thread queue
                        rec_q_list = self._record_queue_list = []
                    else:
                        rec_q_list.append((frame, when))
                        if len(rec_q_list) >= self._record_batch_size:
                            rec_q.put(rec_q_list)  # thread queue
                            rec_q_list = self._record_queue_list = []
                else:
                    if record_start_frame_idx is not None:
                        # end of record/save-to-disk session/mode
                        rec_q_list = self._record_queue_list
                        record_start_frame_idx = None
                        assert isinstance(self._network_queue, FixedArrayMultiQueue)
                        # pad:
                        self._network_queue.pad_cur_batch(self._camera_idx, empty_frame)
                        logger.info("sending EOF_RECORDING frame indices to signify eof recording")
                        for _ in range(self._network_queue.frames_per_camera):
                            while net_q_put(empty_frame, self._camera_idx, FrameIndexCategory.EOF_RECORDING) != BufferResult.Ok:
                                time.sleep(0.001)

                if net_q_put is not None:
                    # network queue goes to processing/inference
                    did_put = net_q_put(frame, self._camera_idx,
                        FrameIndexCategory.ONLINE_NO_RECORDING if record_start_frame_idx is None else cur_frame_idx - record_start_frame_idx,
                        allow_overflow=False) == BufferResult.Ok
                    if did_put:
                        cnt_net_q_put += 1
                    # TODO: we should probably pad the network(online) queue on inference mode changes:
                    # effectively that queue is read by batch of frames.. so we should pad the missing frames in
                    # currently started batch so that the reader won't get that/theses frame(s) some when later...
                    # mixed with newest frames

            except Exception as err:
                logger.exception("Error during capture loop: %s", err)
                self._set_error(err)
                fault_count += 1
                if fault_count > 5:
                    self._end_capture(None)
                    self._user_terminate(None)
        # end while self._is_running

    def _terminate_capture_loop(self):
        try:
            logger.info(f"<{self._name}> capture loop ended")

            self._camera.end_capture()
            VideoManager.close()

            if self._record is not None:
                self._record.cancel()
                self._record.join()

            if self._video_detection is not None:
                self._video_detection.cancel()
                self._video_detection.join()

            self._set_status(CaptureProcessStatus.TERMINATED)

            logger.debug(f"<{self._name}> terminated")
        except Exception as err:
            logger.exception("%s: terminate capture loop error: %s", self, err)
            self._set_error(err)

    def _create_camera(self):
        self._camera = VideoManager.create_camera(self._camera_url, self._name)

    def _handle_command(self, cmd: CaptureCommandKind, context: object):
        logger.info(f"<{self._name}> executing {cmd}")
        self.command_handler.get(cmd)(context)
        logger.debug("status: capturing=%s recording=%s", self._is_capturing, self._is_record_active)

    def _user_terminate(self, _: object):
        self._is_running = False

    def _begin_capture(self, _: object):
        self._is_capturing = True

    def _end_capture(self, _: object):
        self._is_capturing = False

    def _enable_trigger(self, _: object):
        self._is_record_active = self._record_properties.should_record(True)
        logger.debug("%s: is_record_active=%s", self, self._is_record_active)

    def _disable_trigger(self, _: object):
        logger.info("%s: trigger disabled", self)
        self._is_record_active = self._record_properties.should_record(False)
        if len(self._record_queue_list) > 0:
            self._record_queue.put(self._record_queue_list)
            self._record_queue_list = []
        self._record_queue.put([])
