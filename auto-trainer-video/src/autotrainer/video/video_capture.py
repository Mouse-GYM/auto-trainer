from __future__ import annotations

import logging.config
import multiprocessing
import queue
import threading
import time
import signal
from dataclasses import dataclass
from enum import IntEnum
from multiprocessing import Process
from multiprocessing.sharedctypes import Synchronized, SynchronizedArray, SynchronizedString
from typing import Callable, Dict, Union, Optional, List, Tuple

import numpy

from autotrainer.core import FixedArrayMultiQueue, FixedArrayQueue, ProjectInfo, SystemStatusMessageKind
from autotrainer.core.logging import get_verbose_logger, set_logger_level, make_log_dict_config, setup_logging, install_log_exception_hook
from autotrainer.core.frame_index import FrameIndexCategory
from autotrainer.core.fixed_array_queue import BufferResult
from autotrainer.core.video_detection import PresenceDetectionAttrs
from autotrainer.video.video_detection import VideoDetection
from autotrainer.core.capture import CaptureProcessStatus
from .camera.camera_base import CameraBase

from .video_manager import VideoManager
from .video_record import VideoRecord, VideoRecordProperties, VideoRecordMode

logger = get_verbose_logger(__name__)


class CaptureCommandKind(IntEnum):
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

    status: Synchronized[int]
    """Flag for status of the capture process - value is read-only to callers"""

    image_queue: Optional[Union[queue.Queue, FixedArrayQueue]]
    """Queue for camera frame output"""

    frame: Synchronized[int]  # actually unused
    """Current frame index - value is read-only to callers"""

    camera: CaptureCameraAttrs
    """Camera attributes for the capture process"""

    errors: SynchronizedString
    """Multiprocessing string value for communicating errors - value is read-only to callers"""

    synced_cam_record_enabled: Optional[Synchronized[bool]] = None
    """Multiprocessing bool value for communicating recording enabled from primary cam to secondary cam(s)"""

    synced_cam_frame_index: Optional[Synchronized[int]] = None
    """Multiprocessing int value for communicating synced frame index between cameras"""

    inference: Optional[CaptureInferenceAttrs] = None
    """Inference attributes for the capture process (optional)"""

    fps_image_queue: Optional[float] = 15
    """Desired write FPS for the image_queue, if None then default to capture FPS"""

    presence_detection_attrs: Optional[PresenceDetectionAttrs] = None
    """Optional Presence detection"""

    is_primary: bool = False

    msg_queue: Optional[multiprocessing.Queue] = None
    # optional msg queue to send messages to main process from camera process

    record_prebuffer_duration: float = 0

    camera_index: int = -1


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
        log_dict_config = make_log_dict_config()
        super().__init__(
            name=attrs.camera.name,
            target=self._do_run,
            kwargs=dict(log_dict_config=log_dict_config),
            daemon=True,
        )

        self._attrs = attrs
        self._name = attrs.camera.name
        self._camera_url = attrs.camera.url

        self._project_info = project_info
        self._command_queue = attrs.command_queue
        self._command_thread: Optional[threading.Thread] = None
        self._camera_idx = attrs.camera_index
        self._status = attrs.status
        self._image_queue: Optional[Union[queue.Queue, FixedArrayQueue]] = attrs.image_queue
        self._image_queue_frame_delay = None if attrs.fps_image_queue is None else 1 / attrs.fps_image_queue

        self._network_queue: Optional[FixedArrayMultiQueue]
        if attrs.inference is not None:
            self._network_queue = attrs.inference.queue
        else:
            self._network_queue = None

        self._is_record_active = False

        if record_properties is not None:
            self._record_properties = record_properties
            self._is_record_active = record_properties.should_record(False, is_from_start=True)
            self._record_batch_size = record_properties.queue_batch_size
        else:
            self._record_properties = VideoRecordProperties(record_mode=VideoRecordMode.NONE)
            self._record_batch_size = 30

        self._errors = attrs.errors

        self._is_running = True
        self._is_capturing = False
        self._camera = None
        self._record: Optional[VideoRecord] = None
        self._record_queue: Optional[queue.Queue] = None
        self._record_queue_list: List = []

        self._detection_attrs = attrs.presence_detection_attrs
        self._video_detection: Optional[VideoDetection] = None

        self._command_handlers: Dict[CaptureCommandKind, Callable] = {
            CaptureCommandKind.TERMINATE: self._user_terminate,
            CaptureCommandKind.ENABLE_CAPTURE: self._begin_capture,
            CaptureCommandKind.DISABLE_CAPTURE: self._end_capture,
            CaptureCommandKind.ENABLE_RECORDING: self._enable_record,
            CaptureCommandKind.DISABLE_RECORDING: self._disable_record,
            CaptureCommandKind.SET_LOGGER_LEVEL: set_logger_level,
        }

        self._set_status(CaptureProcessStatus.INITIALIZED)

    def _do_run(self, log_dict_config: Optional[Dict]):
        signal.signal(signal.SIGINT, signal.SIG_IGN)

        if log_dict_config is None:
            setup_logging(logger_level=logging.DEBUG)
        else:
            logging.config.dictConfig(log_dict_config)
            install_log_exception_hook()

        logger.info("%s: started running ; name=%s cam_index=%s primary=%s log_dict=%s",
                    self, self._attrs.camera.name, self._camera_idx, self._attrs.is_primary,
                    log_dict_config)
        if not self._prepare_to_run():
            return

        try:
            self._run_capture_loop(self._camera)
        except BaseException as err:
            logger.exception("Fatal error: %s", err)
        self._terminate_capture_loop()

    def _set_status(self, status: CaptureProcessStatus):
        self._status.value = status
        # only relaying start/stop recording equivalent in run_capture_loop method
        # msg_q = self._attrs.msg_queue
        # if self._attrs.is_primary and msg_q is not None:
        #     msg_q.put(status)

    def _set_error(self, error: Exception):
        logger.error("set_error: %s", error)
        self._set_status(CaptureProcessStatus.FAILED)
        if self._errors:
            self._errors.value = f"{error}"[:len(self._errors)].encode()

    def _prepare_to_run(self) -> bool:
        logger.info(f"<{self._name}> process started: %s", self._network_queue)
        try:
            if self._camera_url is None:
                self._set_error(ValueError("camera_url not specified"))
                return False

            try:
                camera = self._camera = VideoManager.create_camera(self._camera_url, self._name)
            except BaseException as err:
                self._set_error(RuntimeError(f"Could not create camera {self._name}: {err}"))
                return False
            camera: CameraBase
            camera.prepare_capture()

            rec_queue = queue.Queue()
            self._record_queue = rec_queue
            self._record_properties.name = self._name
            self._record_properties.frame_size = (camera.width, camera.height)
            self._record_properties.fps = camera.fps

            self._record = VideoRecord(self._record_properties, rec_queue)
            self._record.start()

            if self._detection_attrs is None or self._project_info is None:
                self._video_detection = None
            else:
                self._video_detection = VideoDetection(self._project_info, self._detection_attrs)
                self._video_detection.start()

            logger.verbose("%s: video_detection: %s", self._name, self._video_detection)

            self._command_thread = threading.Thread(target=self._command_handler, daemon=True, name="CommandHandler")
            self._command_thread.start()

            return True
        except Exception as err:
            logger.exception("%s: Error during prepare to run: %s", self, err)
            self._set_status(CaptureProcessStatus.FAILED)
            self._set_error(err)
            return False

    def _command_handler(self):
        while True:
            try:
                raw = self._command_queue.get(timeout=1)
            except queue.Empty:
                continue
            if raw is None:
                self._is_capturing = False
                self._is_running = False
                break
            try:
                cmd, context = raw
                self._handle_command(cmd, context)
            except Exception as err:
                logger.exception("Failure executing cmd %s: %s", raw, err)

    def _run_capture_loop(self, camera: CameraBase) -> None:
        fault_count = 0
        cnt_net_q_put = 0
        cur_frame_idx = -1
        is_record_active = False
        cam_frame_id = -1
        when_secs = None
        attrs = self._attrs
        is_primary = attrs.is_primary
        prim_cam_record_enabled = attrs.synced_cam_record_enabled
        prim_cam_synced_frame_idx = attrs.synced_cam_frame_index
        synced_frame_idx = None
        msg_q = attrs.msg_queue  # message queue to main process
        net_q = self._network_queue  # net_q to pose-process
        record_start_frame_idx = None
        next_t_image_q = time.perf_counter()
        img_q = self._image_queue  # image queue to main/GUI process view
        record_q_list = self._record_queue_list
        record_q = self._record_queue  # record queue to file
        capture = camera.capture
        frame_period = 1 / camera.fps
        net_q_put = None if net_q is None else net_q.put
        net_q_idx = None if net_q_put is None else attrs.inference.index  # although is same than self._camera_idx
        image_queue_delay = self._image_queue_frame_delay
        empty_frame = numpy.zeros(self._record_properties.frame_size, dtype=numpy.uint8)
        vid_detection = self._video_detection

        frames_prebuffer_list: List[Tuple[numpy.ndarray, Union[int, float], float, float, int]] = []
        #                           frame, frame_when, time, perf_now, frame-idx
        def update_frames_prebuffer(f, fw, t, p, fidx):
            idx = 0
            while True:
                if (
                    idx >= len(frames_prebuffer_list)
                    or frame_perf_now - frames_prebuffer_list[idx][3] < attrs.record_prebuffer_duration
                ):
                    break
                idx += 1
            del frames_prebuffer_list[:idx]
            frames_prebuffer_list.append((f, fw, t, p, fidx))

        # primary_acquire/release:
        # Ensure sync, or normal, cameras will use the same frame index for the start frame of all recordings.
        def primary_acquire(frame_idx, enabled):
            nonlocal synced_frame_idx
            if synced_frame_idx is not None:
                return
            if prim_cam_record_enabled is None:  # or attrs.camera_index < 0
                synced_frame_idx = frame_idx - len(frames_prebuffer_list)
                return
            if not is_primary:  # non-primary cams get synced via secondary_acquire()
                return
            target_idx = 1 + frame_idx - len(frames_prebuffer_list)
            # use 1 more to ensure all secondary prebuffers are long enough too
            with prim_cam_record_enabled:  # acquire lock
                synced_frame_idx = target_idx
                prim_cam_synced_frame_idx.value = target_idx
                prim_cam_record_enabled.value = enabled
            logger.debug("Set target frame idx=%s ; frame_idx=%s", target_idx, frame_idx)

        def secondary_acquire():
            nonlocal synced_frame_idx
            if prim_cam_record_enabled is None:
                return
            assert prim_cam_synced_frame_idx is not None
            if not is_primary:
                with prim_cam_record_enabled:
                    synced_frame_idx = prim_cam_synced_frame_idx.value
                logger.debug("got synced frame idx=%s", synced_frame_idx)

        logger.notice("starting capture loop ..")
        self._set_status(CaptureProcessStatus.RUNNING)

        while self._is_running:
            prev_frame_when_secs = when_secs
            prev_frame_id = cam_frame_id

            if fault_count > 5:
                logger.critical("Too many capture loop processing errors ; giving up")
                self._set_error(RuntimeError("too many capture failure"))
                self._end_capture()
                self._user_terminate()
                break

            if is_primary or prim_cam_record_enabled is None:
                # for primary cam or non-synced cam(s):
                is_record_active = self._is_record_active
                # secondary cam reads this value from the primary cam shared flag below.

            t_perf_now = time.perf_counter()
            try:
                if not self._is_capturing:
                    time.sleep(0.001)
                    record_start_frame_idx = None
                    record_q_list = self._record_queue_list = []
                    continue

                # this eventually set/unset recording enabled on the primary cam, or on non-synced cam(s):
                # + 1 because next frame will have that frame_id
                if is_record_active and record_start_frame_idx is None:
                    primary_acquire(prev_frame_id + 1, enabled=True)
                elif not is_record_active and record_start_frame_idx is not None:
                    primary_acquire(prev_frame_id + 1, enabled=False)

                # camera capture:
                frame, when = capture()
                if frame is None:
                    logger.error("Failed to capture a frame (frame = None) ; frame_idx=%s", cur_frame_idx)
                    fault_count += 1
                    continue

                cur_frame_idx += 1
                cam_frame_id = camera.frame_id
                if cam_frame_id is None:
                    if cur_frame_idx == 0:
                        logger.warning("Don't have camera.frame_id, using frame counter")
                    cam_frame_id = cur_frame_idx
                # NB: the frame 'when' can be in different clock than what we can assume,
                # using time.time() and .perf_counter() for precision :
                frame_perf_now = time.perf_counter()
                frame_time = time.time()

                #
                when_secs = when / 1e9
                estimate_dropped = 0 if prev_frame_when_secs is None else int(
                    (when_secs - prev_frame_when_secs - 0.5 * frame_period) / frame_period
                )
                if (
                    net_q is not None
                    and (
                        estimate_dropped > 0
                        or (prev_frame_id is not None and cam_frame_id != prev_frame_id + 1))
                ):
                    logger.warning("frame_idx=%s id=%s (prev=%s) detected frame dropped=%s diff=%.4f prev_when=%.5f frame_when=%.5f",
                                    cur_frame_idx, cam_frame_id, prev_frame_id, estimate_dropped, when_secs - prev_frame_when_secs,
                                   prev_frame_when_secs, when_secs)
                    cur_frame_idx += estimate_dropped

                if cur_frame_idx < 300:
                    if cur_frame_idx == 0:
                        self._record.first_frame_time = frame_time
                        self._record.first_frame_when = when
                        logger.success("captured first frame id=%s ; cam_when=%.4f perf_now=%.4f",
                                       cam_frame_id, when_secs, frame_perf_now)
                    elif net_q is not None and (
                        (cur_frame_idx < 300 and cur_frame_idx % 64 == 0)
                        or (cur_frame_idx < 64 and cur_frame_idx % 16 == 0)
                        or (cur_frame_idx < 32 and cur_frame_idx % 4 == 0)
                        or cur_frame_idx < 4
                    ):
                        logger.debug("got frame %s id=%s cam_when=%.4f perf_now=%.4f",
                                     cur_frame_idx, cam_frame_id, when_secs, frame_perf_now)

                if img_q is not None:
                    # image queue goes to GUI video reader frame, currently FixedArrayQueue
                    if t_perf_now >= next_t_image_q:
                        if image_queue_delay is not None:
                            next_t_image_q = t_perf_now + image_queue_delay
                        if len(numpy.shape(frame)) < 3:
                            img_q.put(frame)
                        else:
                            img_q.put(frame[:, :, 0])

                if prim_cam_record_enabled is not None and not is_primary:
                    # for secondary synced cams we don't have other choice than to read
                    # the primary cam recording enabled shared flag on each frame read:
                    is_record_active = prim_cam_record_enabled.value

                # record queue goes to video save to disk/file
                if is_record_active and record_start_frame_idx is None:
                    secondary_acquire()
                    if synced_frame_idx is not None:
                        record_start_frame_idx = synced_frame_idx
                        synced_frame_idx = None
                    if record_start_frame_idx is not None:
                        record_start_frame_idx: int
                        cut_idx = 0
                        # use the frame_id to be sure:
                        while cut_idx < len(frames_prebuffer_list):
                            if frames_prebuffer_list[cut_idx][-1] >= record_start_frame_idx:
                                break
                            cut_idx += 1
                        if cut_idx > 0:
                            logger.debug(
                                "cutting frames_prebuffer_list by %s ; cur_frame_idx=%s len(prebuff)=%s",
                                cut_idx,
                                cur_frame_idx,
                                len(frames_prebuffer_list),
                            )
                            del frames_prebuffer_list[:cut_idx]
                        #
                        first_frame_id = (
                            cam_frame_id if len(frames_prebuffer_list) == 0
                            else frames_prebuffer_list[0][-1]
                        )
                        first_frame_when = (
                            when
                            if len(frames_prebuffer_list) == 0
                            else frames_prebuffer_list[0][1]
                        )
                        first_frame_time = (
                            frame_time
                            if len(frames_prebuffer_list) == 0
                            else frames_prebuffer_list[0][2]
                        )
                        first_frame_p_now = (
                            frame_perf_now
                            if len(frames_prebuffer_list) == 0
                            else frames_prebuffer_list[0][3]
                        )
                        logger.notice(
                            "Starting record with frame_idx=%s cam_frame_id=%s perf_now=%.4f when=%.4f ; prebuffer_cnt=%s",
                            record_start_frame_idx, first_frame_id,
                            first_frame_p_now, first_frame_when / 1e9,
                            len(frames_prebuffer_list),
                        )
                        #
                        self._record.first_frame_when = first_frame_when
                        self._record.first_frame_time = first_frame_time
                        #
                        if len(frames_prebuffer_list) > 0:
                            record_q.put(
                                [(f, fw, p) for f, fw, _, p, _ in frames_prebuffer_list]
                            )
                            frames_prebuffer_list = []  # reminder: don't use .clear(): record_q is thread queue
                        record_q.put([(frame, when, frame_perf_now)])  # thread queue
                        record_q_list = (
                            self._record_queue_list
                        ) = []  # ensure we (re)start clean

                        #
                        self._set_status(CaptureProcessStatus.RECORDING)

                        if is_primary and msg_q is not None:
                            if __debug__:
                                logger.debug("is_primary: Putting CaptureProcessStatus.RECORDING")
                            msg_q.put((SystemStatusMessageKind.CAMERA_STATUS_CHANGE,
                                       (self._camera_idx, CaptureProcessStatus.RECORDING)))
                        else:
                            if __debug__:
                                logger.debug("not is_primary or msg_q None"
                                             " ; skipped put CaptureProcessStatus.RECORDING")

                elif not is_record_active and record_start_frame_idx is not None:
                    secondary_acquire()
                    # stop recording requested
                    if synced_frame_idx is not None and cam_frame_id >= synced_frame_idx:
                        record_start_frame_idx = None
                        synced_frame_idx = None

                    if record_start_frame_idx is None:
                        record_q_list = self._record_queue_list
                        if len(record_q_list) > 0:
                            record_q.put(record_q_list)
                            record_q_list = self._record_queue_list = []
                        record_q.put([])

                        if net_q is not None:
                            # we might eventually have written some extra frame(s) vs the other camera(s) used in
                            # the net_q, so this pad_to_batch_size :
                            net_q.pad_to_batch_size(net_q_idx, empty_frame, cnt_net_q_put, timeout=5)
                            # required: must set back to 0 given will now be same in all cams,
                            # and also aligned with frames_per_camera_per_batch
                            cnt_net_q_put = 0
                            # now
                            logger.info(
                                "sending EOF_RECORDING batch frame indices to signify eof recording. "
                                "last frame index: %s when=%.4f perf=%.4f",
                                cur_frame_idx, when / 1e9, frame_perf_now)
                            net_q.put_frame_index_category(empty_frame, FrameIndexCategory.EOF_RECORDING,
                                                           cam_idx=net_q_idx, timeout=1)

                        self._set_status(CaptureProcessStatus.RUNNING)

                        if is_primary and msg_q is not None:
                            msg_q.put((SystemStatusMessageKind.CAMERA_STATUS_CHANGE,
                                       (self._camera_idx, CaptureProcessStatus.RUNNING)))

                elif is_record_active and record_start_frame_idx is not None:
                    # normal recording case in progress
                    record_q_list.append((frame, when, frame_perf_now))
                    if len(record_q_list) >= self._record_batch_size:
                        record_q.put(record_q_list)
                        record_q_list = self._record_queue_list = []

                if net_q_put is not None:
                    # network queue goes to processing/inference
                    frame_idx_cat = (
                        FrameIndexCategory.ONLINE_NO_RECORDING if record_start_frame_idx is None
                        else cur_frame_idx - record_start_frame_idx
                    )
                    if net_q_put(frame, net_q_idx, frame_idx_cat, block=False) == BufferResult.Ok:
                        cnt_net_q_put += 1

                if vid_detection is not None:
                    vid_detection.update_frame(when, frame, frame_perf_now)

                if not (is_record_active and record_start_frame_idx is not None) and attrs.record_prebuffer_duration > 0:
                    update_frames_prebuffer(frame, when, frame_time, frame_perf_now, cam_frame_id)

            except Exception as err:
                logger.exception("Error during capture loop: %s", err)
                self._set_error(err)
                fault_count += 1

        # end while self._is_running

    def _terminate_capture_loop(self):
        try:
            logger.info(f"<{self._name}> capture loop ended")

            self._camera.end_capture()

            vid_rec = self._record
            if vid_rec is not None:
                vid_rec.cancel()
                logger.debug("joining record thread")
                vid_rec.join()
                self._record = None

            video_detection = self._video_detection
            if video_detection is not None:
                video_detection.cancel()
                logger.debug("joining video-detection thread")
                video_detection.join()
                self._video_detection = None

            logger.debug("joining command thread")
            thread = self._command_thread
            if thread is not None:
                if thread.is_alive():
                    self._command_queue.put(None)
                thread.join()

        except Exception as err:
            logger.exception("%s: terminate capture loop error: %s", self, err)
            self._set_error(err)
        finally:
            logger.debug("terminated")
            self._set_status(CaptureProcessStatus.TERMINATED)

    def _handle_command(self, cmd: CaptureCommandKind, context: object):
        logger.info("executing %s", cmd)
        handler = self._command_handlers.get(cmd)
        if handler is None:
            logger.warning("No handler for command %s", cmd)
        else:
            args, kwargs = context
            handler(*args, **kwargs)
            logger.debug("status: capturing=%s recording=%s", self._is_capturing, self._is_record_active)

    def _user_terminate(self):
        self._is_running = False

    def _begin_capture(self):
        self._is_capturing = True

    def _end_capture(self):
        self._is_capturing = False

    def _enable_record(self, *, is_from_start: bool=False):
        self._is_record_active = self._record_properties.should_record(True, is_from_start=is_from_start)
        logger.verbose("_enable_record: is_record_active=%s", self._is_record_active)

    def _disable_record(self, *, is_triggered: Optional[bool]=False, is_from_start: bool=False):
        entry_is_triggered = is_triggered
        if is_triggered is None:
            is_triggered = self._is_record_active
        self._is_record_active = self._record_properties.should_record(is_triggered, is_from_start=is_from_start)
        logger.verbose("_disable_record(is_triggered=%s, is_from_start=%s): is_record_active=%s",
                       entry_is_triggered, is_from_start, self._is_record_active)
