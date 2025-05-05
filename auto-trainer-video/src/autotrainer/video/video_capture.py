from __future__ import annotations

import logging
import queue
import time
from dataclasses import dataclass
from queue import Queue
from enum import Enum, IntEnum
from multiprocessing import Process, Value, Array
from typing import Callable, Dict

import numpy

from autotrainer.core import FixedArrayMultiQueue, FixedArrayQueue

from .video_manager import VideoManager
from .video_record import VideoRecord, VideoRecordProperties, VideoRecordMode

logger = logging.getLogger(__name__)


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
    queue: Queue | FixedArrayMultiQueue
    index: int


@dataclass
class CaptureAttrs:
    """
    Attributes for VideoCapture configuration
    """
    command_queue: Queue
    """Input queue for submitting commands to the capture process"""
    status: Value
    """Flag for status of the capture process - value is read-only to callers"""
    image_queue: Queue | FixedArrayQueue | None
    """Queue for camera frame output"""
    frame: Value
    """Current frame index - value is read-only to callers"""
    camera: CaptureCameraAttrs
    """Camera attributes for the capture process"""
    inference: CaptureInferenceAttrs = None
    """Inference attributes for the capture process (optional)"""
    errors: Array = None
    """Multiprocessing Array for communicating errors - value is read-only to callers"""


class VideoCapture(Process):
    """
    Process-based class for video capture and recording.

    VideoCapture runs as a separate process for video capture and recording.  An optional image queue can be provided
    to receive frames from the camera.  A separate, optional pellet queue can be provided to feed pellet models
    or any other process.
    """

    def __init__(self, attrs: CaptureAttrs, record_properties: VideoRecordProperties = None):
        super().__init__(name=attrs.camera.name)

        self._name = attrs.camera.name
        self._camera_url = attrs.camera.url

        self._command_queue = attrs.command_queue
        self._status = attrs.status
        self._image_queue = attrs.image_queue

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
        self._record_queue = None

        # Buffered send to record queue
        self._queue_list = list()
        self._queue_list_count = 0

        self.command_handler: Dict[CaptureCommandKind, Callable[[object], None]] = {
            CaptureCommandKind.TERMINATE: self._user_terminate,
            CaptureCommandKind.ENABLE_CAPTURE: self._begin_capture,
            CaptureCommandKind.DISABLE_CAPTURE: self._end_capture,
            CaptureCommandKind.ENABLE_RECORDING: self._enable_trigger,
            CaptureCommandKind.DISABLE_RECORDING: self._disable_trigger
        }

        self._set_status(CaptureProcessStatus.INITIALIZED)

    def run(self):
        if not self._prepare_to_run():
            return

        self._run_capture_loop()

        self._terminate_capture_loop()

    def _set_status(self, status: CaptureProcessStatus):
        self._status.value = status

    def _set_error(self, error: Exception):
        logger.error(f"<{self._name}> {error}")

        self._set_status(CaptureProcessStatus.FAILED)

        if self._errors:
            self._errors.value = f"{error}"[:len(self._errors)].encode()

    def _prepare_to_run(self) -> bool:
        try:
            logger.debug(f"<{self._name}> process started")

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

            self._set_status(CaptureProcessStatus.RUNNING)

            return True
        except Exception as ex:
            self._set_error(ex)
            return False

    def _run_capture_loop(self) -> None:
        fault_count = 0

        while self._is_running:
            try:
                if self._command_queue is not None:
                    try:
                        cmd, context = self._command_queue.get_nowait()
                        self._handle_command(cmd, context)
                    except queue.Empty:
                        pass

                if not self._is_capturing:
                    # Unclear how universal this is, but the combination of [Jetson, JetPack 5, Ubuntu 20, Python] will
                    # massively slow down the system without explicitly yielding, despite being in its own thread.  This
                    # not the case for other platforms/combinations of the above so may not be apparent when not on the
                    # current deployment platform.
                    time.sleep(0.001)
                    continue

                frame, when = self._camera.capture()

                if self._image_queue is not None:
                    if len(numpy.shape(frame)) < 3:
                        self._image_queue.put(frame)
                    else:
                        self._image_queue.put(frame[:, :, 0])

                if self._is_record_active:
                    self._queue_list.append((frame, when))
                    self._queue_list_count += 1
                    if self._queue_list_count >= self._record_batch_size:
                        self._record_queue.put(self._queue_list)
                        self._queue_list = list()
                        self._queue_list_count = 0

                if self._network_queue is not None:
                    self._network_queue.put(frame, self._camera_idx)
            except Exception as ex:
                self._set_error(ex)
                fault_count += 1
                if fault_count > 5:
                    self._end_capture(None)
                    self._user_terminate(None)

    def _terminate_capture_loop(self):
        try:
            logger.debug(f"<{self._name}> capture loop ended")

            self._camera.end_capture()

            VideoManager.close()

            if self._record is not None:
                self._record.cancel()
                self._record.join()

            self._set_status(CaptureProcessStatus.TERMINATED)

            logger.debug(f"<{self._name}> terminated")
        except Exception as ex:
            self._set_error(ex)

    def _create_camera(self):
        self._camera = VideoManager.create_camera(self._camera_url, self._name)

    def _handle_command(self, cmd: CaptureCommandKind, context: object):
        logger.debug(f"<{self._name}> received {cmd}")

        self.command_handler.get(cmd)(context)

    def _user_terminate(self, _: object):
        self._is_running = False

    def _begin_capture(self, _: object):
        self._is_capturing = True

    def _end_capture(self, _: object):
        self._is_capturing = False

    def _enable_trigger(self, _: object):
        self._queue_list = list()
        self._queue_list_count = 0
        self._is_record_active = self._record_properties.should_record(True)

    def _disable_trigger(self, _: object):
        self._is_record_active = self._record_properties.should_record(False)
        # self._record_queue.put((None, None))
        self._queue_list = list()
        self._queue_list_count = 0
        self._record_queue.put(list())
