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
from threading import BrokenBarrierError
from typing import Callable, Dict, Union, Optional, List

import numpy
import verboselogs

from autotrainer.core import FixedArrayMultiQueue, FixedArrayQueue, ProjectInfo, SystemStatusMessageKind
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

    TERMINATED = -2
    """The capture loop is terminated"""

    FAILED = -1
    """Failed to configure or run process"""

    UNKNOWN = 0
    """Uninitialized value not yet set by capture process"""

    INITIALIZED = 1
    """The process is created, but not started"""

    RUNNING = 2
    """The process is running the capture loop"""

    RECORDING = 3
    """The process is recording the stream to disk"""


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

    is_primary: bool = False

    msg_queue: Optional[multiprocessing.Queue] = None
    # optional msg queue to send messages to main process from camera process


class VideoCapture(Process):
    """
    Process-based class for video capture and recording.

    VideoCapture runs as a separate process for video capture and recording.  An optional image queue can be provided
    to receive frames from the camera.  A separate, optional pellet queue can be provided to feed pellet models
    or any other process.
    """

    _network_queue: Optional[FixedArrayMultiQueue]

    def __init__(
        self,
        attrs: CaptureAttrs,
        record_properties: Optional[VideoRecordProperties] = None,
        project_info: Optional[ProjectInfo] = None,
    ):
        super().__init__(name=attrs.camera.name)

        self._attrs = attrs
        self._name = attrs.camera.name
        self._camera_url = attrs.camera.url

        self._project_info = project_info
        self._command_queue = attrs.command_queue
        self._status = attrs.status
        self._image_queue: Optional[Union[Queue, FixedArrayQueue]] = attrs.image_queue
        self._image_queue_frame_delay = None if attrs.fps_image_queue is None else 1 / attrs.fps_image_queue

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
        self._record: VideoRecord = None
        self._record_queue: Optional[Queue] = None
        self._record_queue_list: List = []

        self._detection_attrs = attrs.presence_detection_attrs

        self.command_handler: Dict[CaptureCommandKind, Callable[[object], None]] = {
            CaptureCommandKind.TERMINATE: self._user_terminate,
            CaptureCommandKind.ENABLE_CAPTURE: self._begin_capture,
            CaptureCommandKind.DISABLE_CAPTURE: self._end_capture,
            CaptureCommandKind.ENABLE_RECORDING: self._enable_record,
            CaptureCommandKind.DISABLE_RECORDING: self._disable_record,
            CaptureCommandKind.SET_LOGGER_LEVEL: set_logger_level,
        }

        self._set_status(CaptureProcessStatus.INITIALIZED)

    def run(self):
        from autotrainer.core.logging import setup_logging
        log_level = os.getenv("VIDEO_CAPTURE_LOG_LEVEL", verboselogs.VERBOSE)
        if isinstance(log_level, str) and log_level.isdigit():
            log_level = int(log_level)
        setup_logging(root_level=log_level, time_precision=6)

        logger.info("%s: started running ; name=%s cam_index=%s primary=%s",
                    self, self._attrs.camera.name, self._camera_idx, self._attrs.is_primary)
        if not self._prepare_to_run():
            return

        self._run_capture_loop()
        self._terminate_capture_loop()

    def _set_status(self, status: CaptureProcessStatus):
        self._status.value = status
        msg_q = self._attrs.msg_queue
        if self._attrs.is_primary and msg_q is not None:
            msg_q.put(status)

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
        is_primary = self._attrs.is_primary
        msg_q = self._attrs.msg_queue  # message queue to main process
        net_q = self._network_queue
        record_start_frame_idx = None
        next_t_image_q = time.time()
        next_t_cmd_q = next_t_image_q
        img_q = self._image_queue
        record_q_list = self._record_queue_list
        record_q = self._record_queue
        capture = self._camera.capture
        net_q_put = None if self._network_queue is None else self._network_queue.put
        image_queue_delay = self._image_queue_frame_delay
        get_command = None if self._command_queue is None else self._command_queue.get_nowait
        empty_frame = numpy.zeros(self._record_properties.frame_size, dtype=numpy.uint8)
        vid_detection = self._video_detection

        released = False
        primary_acquired_count = 0

        if net_q is None:
            sync_barrier = lambda timeout=None: None
            primary_sema = None
            primary_acquire = lambda: True
            primary_release = lambda: None
        else:
            primary_sema = net_q.semaphore

            def sync_barrier(timeout=5, *, wait_barrier=net_q.barrier.wait):
                try:
                    wait_barrier(timeout=timeout)
                except BrokenBarrierError:
                    logger.critical("multiproc network queue barrier broken")
                    raise

            def primary_acquire():
                nonlocal primary_acquired_count, released
                if is_primary:
                    for _ in range(net_q.camera_count - primary_acquired_count - 1):
                        if primary_sema.acquire(timeout=0):
                            primary_acquired_count += 1
                            logger.debug("sem acquired, current=%s", primary_acquired_count)
                    if primary_acquired_count == net_q.camera_count - 1:
                        logger.debug("all sem acquired, count=%s sem_val=%s ; now setting event",
                                       primary_acquired_count, primary_sema.get_value())
                        net_q.event.set()
                    return primary_acquired_count == net_q.camera_count - 1
                else:
                    if not released:
                        primary_sema.release()
                        __debug__ and logger.debug("sem released")
                        released = True
                    if net_q.event.wait(0.001):
                        __debug__ and logger.debug("event obtained")
                        return True
                    return False

            def primary_release():
                nonlocal primary_acquired_count, released
                if is_primary:
                    # barrier eventually necessary if non-primary cams are doing sync_barrier before frame read
                    sync_barrier()
                    __debug__ and logger.debug("acquiring %s times before release", primary_acquired_count)
                    for _ in range(primary_acquired_count):
                        primary_sema.acquire()  # ensure we clear after all other(s) cam(s) have released
                    __debug__ and logger.debug("primary clearing event ; sem_val=%s", primary_sema.get_value())
                    # after the above acquire:
                    net_q.event.clear()  # must also be after the before acquire. to ensure all cams get
                    # a chance to see the event flag
                    primary_acquired_count = 0
                    __debug__ and logger.debug("primary released ; val=%s", primary_sema.get_value())
                else:
                    __debug__ and logger.debug("not primary releasing")
                    primary_sema.release()
                    sync_barrier()
                    __debug__ and logger.debug("not primary released")
                    released = False

        first_frame_when = 0

        logger.notice("%s: starting capture loop ..", self)
        while self._is_running:
            t_now = time.time()
            try:
                if get_command is not None and t_now >= next_t_cmd_q:
                    cmd = None
                    try:
                        cmd, context = get_command()
                        self._handle_command(cmd, context)
                    except queue.Empty:
                        next_t_cmd_q = t_now + 0.02  # no need check that often
                        # we now use mp barrier to sync when needed
                    except Exception as err:
                        logger.exception("Failure executing cmd %s: %s", cmd, err)
                    record_q_list = self._record_queue_list

                if not self._is_capturing:
                    time.sleep(0.001)
                    record_start_frame_idx = None
                    record_q_list = self._record_queue_list = []
                    next_t_cmd_q = t_now  # force get on next turn
                    continue

                # ensure primary capture first
                if not is_primary and cur_frame_idx == -1:
                    sync_barrier()

                frame, when = capture()

                perf_now_ns = time.perf_counter_ns()
                if cur_frame_idx == -1:
                    if is_primary:
                        sync_barrier()

                    logger.info("%s: captured first frame ; when=%s perf_now=%s", self,
                                when, perf_now_ns)

                cur_frame_idx += 1
                when -= first_frame_when  # ensure all cams are synced on "0"

                if img_q is not None:
                    # image queue goes to GUI video reader frame, currently FixedArrayQueue
                    if t_now >= next_t_image_q:
                        if image_queue_delay is not None:
                            next_t_image_q = t_now + image_queue_delay
                        if len(numpy.shape(frame)) < 3:
                            img_q.put(frame)
                        else:
                            img_q.put(frame[:, :, 0])

                # record queue goes to video save to disk/file
                if self._is_record_active and record_start_frame_idx is None:
                    if primary_acquire():
                        logger.notice("Starting record with frame %s when=%s perf_now=%s",
                                      cur_frame_idx, when, time.perf_counter_ns())
                        record_start_frame_idx = cur_frame_idx
                        first_frame_when = when
                        when -= first_frame_when
                        record_q.put([(frame, when, perf_now_ns)])  # thread queue
                        record_q_list = self._record_queue_list = []
                        #
                        primary_release()

                        if is_primary and msg_q is not None:
                            msg_q.put((SystemStatusMessageKind.CAMERA_STATUS_CHANGE,
                                       (self._camera_idx, CaptureProcessStatus.RECORDING)))

                elif not self._is_record_active and record_start_frame_idx is not None:
                    # stop recording requested
                    record_q_list = self._record_queue_list
                    if not primary_acquire():
                        # continue, all sync cams have not yet received their stop recording message
                        record_q_list.append((frame, when, perf_now_ns))
                    else:
                        # end of record/save-to-disk session/mode
                        primary_release()
                        first_frame_when = 0
                        record_start_frame_idx = None
                        if len(record_q_list) > 0:
                            record_q.put(record_q_list)
                            record_q_list = self._record_queue_list = []
                        record_q.put([])
                        # wait record file is closed:
                        self._record.close_event.wait()
                        # so that when session analyse is enabled the feeder thread won't try to open the mp4 files
                        # before so.

                        if net_q is not None:
                            logger.verbose(
                                "sending EOF_RECORDING frame indices to signify eof recording. "
                                "last frame index: %s when=%s perf_now=%s",
                                cur_frame_idx, when, time.perf_counter_ns())

                            # time.sleep(0.2)
                            # this is to help ensure consumer has finished reading current frames that are already pushed
                            # is not big issue to sleep here given this is not hot code path

                            sync_barrier()
                            # set the tot_frames in different sync_barrier session than the next get_cam_missing_frames
                            net_q.set_cam_tot_frames(self._camera_idx, cnt_net_q_put)
                            cnt_net_q_put = 0
                            # convenience: can set back to 0 given will now be same in all cams,
                            # and also aligned with frames_per_camera_per_batch

                            sync_barrier()
                            d = net_q.get_cam_missing_frames(self._camera_idx)
                            sync_barrier()

                            # logger.debug("padding %s times", d)
                            timeout = 10
                            for _ in range(d):
                                t0 = time.perf_counter()
                                net_q.put_block(empty_frame, self._camera_idx, FrameIndexCategory.PADDING,
                                                timeout=timeout)
                                timeout -= time.perf_counter() - t0
                            for _ in range(self._network_queue.frames_per_camera):
                                t0 = time.perf_counter()
                                net_q.put_block(empty_frame, self._camera_idx, FrameIndexCategory.EOF_RECORDING,
                                                timeout=timeout)
                                timeout -= time.perf_counter() - t0

                            sync_barrier()

                        if is_primary and msg_q is not None:
                            msg_q.put((SystemStatusMessageKind.CAMERA_STATUS_CHANGE,
                                       (self._camera_idx, CaptureProcessStatus.RUNNING)))

                elif self._is_record_active and record_start_frame_idx is not None:
                    # normal recording case
                    record_q_list.append((frame, when, perf_now_ns))
                    if len(record_q_list) >= self._record_batch_size:
                        record_q.put(record_q_list)
                        record_q_list = self._record_queue_list = []

                if net_q_put is not None:
                    # network queue goes to processing/inference
                    did_put = net_q_put(frame, self._camera_idx,
                        FrameIndexCategory.ONLINE_NO_RECORDING if record_start_frame_idx is None
                        else cur_frame_idx - record_start_frame_idx,
                        allow_overflow=False) == BufferResult.Ok
                    if did_put:
                        cnt_net_q_put += 1
                    # TODO: we should probably pad the network(online) queue on inference mode changes:
                    # effectively that queue is read by batch of frames.. so we should pad the missing frames in
                    # currently started batch so that the reader won't get that/theses frame(s) some when later...
                    # mixed with newest frames

                if vid_detection is not None:
                    vid_detection.update_frame(when, frame)

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

    def _enable_record(self, _: object):
        self._is_record_active = self._record_properties.should_record(True)
        logger.info("%s: is_record_active=%s", self, self._is_record_active)

    def _disable_record(self, _: object):
        self._is_record_active = self._record_properties.should_record(False)
        logger.info("%s: recording disabled. is_record_active=%s", self, self._is_record_active)
