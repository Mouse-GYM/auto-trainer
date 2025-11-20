import logging.config
import multiprocessing
import os
import queue
import signal
import threading
import time
import typing
from itertools import chain
from pathlib import Path
from typing import Optional, List, Dict, TextIO, Tuple
from threading import Thread

import cv2
import h5py
import numpy
import numpy as np

from autotrainer.core import FixedArrayMultiQueue, ProjectInfo, EventManager, clear_queue, \
    InferenceConfiguration, Offset3DTuple, ApiEventKind
from autotrainer.core.logging import get_verbose_logger, setup_logging, make_log_dict_config, install_log_exception_hook
from autotrainer.behavior import SegmentationConfiguration, DetectionConfiguration, \
    InferenceProtocol, IntersessionBlock, IntersessionDetection
from autotrainer.core.message import FrameIndexCategory
from autotrainer.core.multiproc import get_mp_ctx
from autotrainer.inference import PoseProcess, InferenceCommandMessageKind, InferenceStatusMessageKind, PoseAlgorithm, \
    InferenceMode, InferenceStatus
from autotrainer.core.pose_elements import SceneElement, AllHandsParts
from autotrainer.inference.pose_result_process import InferenceMonitorDataProc
from autotrainer.inference.analysis import intersession_process

from tools.acquisition.model.project_dependent_protocol import ProjectDependentProtol


logger = get_verbose_logger(__name__)


# even better is to use __debug__ and use "python -O ..."
# see https://docs.python.org/3/using/cmdline.html#cmdoption-O
_local_do_debug = False


def check_frame_count(file_path: Path):
    capture = cv2.VideoCapture(file_path.as_posix())
    count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if count < 1:
        capture.release()
        return None, None
    logger.verbose("Opened %s: tot_frames=%s size=%s", file_path.name, count, file_path.stat().st_size)
    return capture, count


def _pool_init(log_dict_cfg):
    """For process pool below"""
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    if log_dict_cfg is None:
        setup_logging()
    else:
        logging.config.dictConfig(log_dict_cfg)
        install_log_exception_hook()
    logger.info("Initialized pool worker")


class InferenceModel(InferenceProtocol, ProjectDependentProtol):

    def __init__(self,
        pose_algorithm: PoseAlgorithm,
        *,
        calib_dir: Optional[Path] = None,
    ):
        super().__init__()

        mp_ctx = get_mp_ctx()
        self._thread_lock = threading.RLock()  # for perform_detection / perform_segmentation
        self._data_queue = mp_ctx.Queue(maxsize=64)  # inference result data queue
        self._inference_cmd_queue = mp_ctx.Queue(maxsize=16)  # command queue to inference process
        self._msg_queue = mp_ctx.Queue(maxsize=64)
        self._data_monitor_cmd_queue = mp_ctx.Queue(maxsize=16)

        self._offline_queue: Optional[FixedArrayMultiQueue] = None
        self._offline_thread: Optional[Thread] = None

        self._is_enabled = False
        self._model_location = ""
        self._algorithm = pose_algorithm
        # self._algorithm.pose_changed += self._pose_changed
        # no need, we have the pose response in the monitor data queue function
        self._calib_dir = calib_dir

        self._msg_thread = None
        self._data_monitor_proc: Optional[InferenceMonitorDataProc] = None

        self._pose_process: Optional[PoseProcess] = None
        self._is_predict_enabled = True
        self._status = InferenceStatus.stopped

        self._frames_per_camera = 0
        self._frame_width = 1
        self._frame_height = 1

        self._intersession_wait_time: float = 1.0

        self._project: Optional[ProjectInfo] = None
        self._intersession_block: Optional[IntersessionBlock] = None
        self._intersession_detection: Optional[IntersessionDetection] = None
        self._parts_offsets: Dict[Tuple[SceneElement, SceneElement], Offset3DTuple] = {}
        self._pair_offsets_2_handler = {
            (SceneElement.Diamond, SceneElement.Triangle): self.diamond_triangle_offset_changed,
            (SceneElement.Star, SceneElement.Triangle): self.star_triangle_offset_changed,
            (SceneElement.Triangle, SceneElement.Pellet): self.triangle_pellet_offset_changed,
            **{
                (SceneElement.Pellet, hand_part): lambda _: None  # this will be sub-handled in behavior algo
                for hand_part in AllHandsParts
            },
        }
        self._process_pool: Optional[multiprocessing.Pool] = None

    @property
    def project(self) -> ProjectInfo:
        return self._project

    @project.setter
    def project(self, value: ProjectInfo):
        self._project = value
        logger.debug("Putting new project info to data monitor queue: %s", value)
        self._data_monitor_cmd_queue.put(
            (InferenceMonitorDataProc.Msg.SET_PROJECT_INFO, (value,), None))

    @property
    def is_enabled(self) -> bool:
        return self._is_enabled

    @is_enabled.setter
    def is_enabled(self, value: bool):
        self._is_enabled = self._on_property_changed("is_enabled", value, self._is_enabled)

    @property
    def is_predict_enabled(self) -> bool:
        return self._is_predict_enabled

    @is_predict_enabled.setter
    def is_predict_enabled(self, value: bool):
        self._is_predict_enabled = self._on_property_changed("is_predict_enabled", value, self._is_predict_enabled)

    @property
    def model_location(self) -> str:
        return self._model_location

    @model_location.setter
    def model_location(self, value: str):
        self._model_location = self._on_property_changed("model_location", value, self._model_location)

    @property
    def intersession_wait_time(self) -> float:
        return self._intersession_wait_time

    @intersession_wait_time.setter
    def intersession_wait_time(self, value: float):
        self._intersession_wait_time = self._on_property_changed("intersession_wait_time", value,
                                                                 self._intersession_wait_time)

    @property
    def status(self) -> InferenceStatus:
        return self._status

    @property
    def pose_algorithm(self) -> PoseAlgorithm:
        return self._algorithm

    def _check_previous_offline_thread(self, cause: str):
        cur_off = self._offline_thread
        if cur_off is not None:
            # protection, if we need more than 1 executing thread at the same time then we need a list to retain the
            # threads instead of only one of them.
            perf_now = time.perf_counter()
            was_alive = cur_off.is_alive()
            if was_alive:
                logger.warning("%s request but previous offline thread still alive: %s, join might block ~long",
                               cause, cur_off)
            cur_off.join()
            self._offline_thread = None
            if was_alive:
                logger.verbose("Waited %.1fs to join previous offline thread", time.perf_counter() - perf_now)

    def perform_segmentation(self, configuration: SegmentationConfiguration):
        with self._thread_lock:
            return self._perform_segmentation(configuration)

    def _perform_segmentation(self, configuration: SegmentationConfiguration):
        offline_thread = self._offline_thread
        if self._intersession_block is not None:
            logger.warning("_intersession_block not None, segmentation already started. block=%s segment_cfg=%s",
                           self._intersession_block, configuration)
            if offline_thread is not None and not offline_thread.is_alive():
                logger.info("But offline thread not running, continuing")
            else:
                return None
        self._check_previous_offline_thread("perform_segmentation")
        self._data_monitor_proc.stop_recorded.clear()
        logger.info("performing segmentation on %s", configuration)
        intersession_block = self._intersession_block = IntersessionBlock(configuration=configuration)

        self._send_message(InferenceCommandMessageKind.ProcessOffline)
        # ProcessOffline is not anymore used.
        # the trigger for pose process to switch to offline queue processing is now delivered by
        # camera capture itself, which send an EOF_RECORDING when a video/session record finishes.

        # once the message is sent, also wait a bit,
        # this is to give some time to inference process to switch to offline queue,
        # and also reset its offline read queue side:
        # time.sleep(0.5)
        # Not anymore needed, see video_capture and below __feed_intersession_analysis.
        self._offline_thread = Thread(
            target=self._feed_intersession_analysis,
            args=(intersession_block,),
            name="feed_intersession_analysis",
        )
        # but then, wait again a bit of more time.
        # this is to give some time to the monitor data queue thread, to get/detect the end of recording in progress,
        # and switch to offline processing request (which is coming indirectly from the pose process),
        # and get a chance to close the "h5-live" and frames-idx-already-processed file handles.
        # time.sleep(0.5)
        # NB: this might not be enough though, we probably should use a threading event (with a timeout eventually)
        # Now using thread event.
        self._offline_thread.start()
        return configuration

    def perform_detection(self, configuration: DetectionConfiguration):
        with self._thread_lock:
            return self._perform_detection(configuration)

    def _perform_detection(self, configuration: DetectionConfiguration):
        if self._intersession_detection is not None:
            logger.warning("_intersession_detection not None, skipping perform_detection")
            return None
        logger.info("performing detection analysis on %s", configuration)
        self._check_previous_offline_thread("perform_detection")
        intersession_detection = self._intersession_detection = IntersessionDetection(configuration)
        project = self._project
        self._offline_thread = Thread(target=self._intersession_process, name="intersession_process",
                                      args=(project, intersession_detection,))
        self._offline_thread.start()
        return configuration

    def set_inference_to_online(self):
        offline_queue = self._offline_queue
        if offline_queue is not None:
            ib = self._intersession_block
            if ib is not None:
                logger.warning("set_inference_to_online but intersession block: %s", ib)
            else:
                logger.notice("Setting inference back to online with SWITCH_TO_ONLINE")
                empty = numpy.zeros(offline_queue.shape, dtype=numpy.uint8)
                # should pad in case the cams index are unsync...
                # self._offline_queue.pad_to_batch_size(empty)
                # NO: the offline queue should be always sync, as only 1 writer at the same time.
                self._offline_queue.put_frame_index_category(empty, FrameIndexCategory.SWITCH_TO_ONLINE)

    def start(self, live_queue: FixedArrayMultiQueue) -> bool:

        self._process_pool = multiprocessing.Pool(
            processes=1,  # we only need 1 atm
            initializer=_pool_init,
            initargs=(make_log_dict_config(),),
            maxtasksperchild = int(os.getenv("INFERENCE_PROCESS_POOL_MAX_TASKS_PER_CHILD", 4096)),
        )

        if self._msg_thread is None:
            self._msg_thread = Thread(target=self._monitor_msg_queue, name="monitor_msg_queue", daemon=True)
            self._msg_thread.start()

        if self._data_monitor_proc is None:
            proc = self._data_monitor_proc = InferenceMonitorDataProc(
                project=self._project,
                pose_data_queue=self._data_queue,
                msg_queue=self._msg_queue,
                cmd_queue=self._data_monitor_cmd_queue,
                frames_per_cam=live_queue.frames_per_camera,
                monitored_parts_offsets=list(self._pair_offsets_2_handler),
            )
            proc.start()

        self._frame_height, self._frame_width = live_queue.shape
        self._frames_per_camera = live_queue.frames_per_camera

        self._offline_queue = FixedArrayMultiQueue(
            # offline queue can have a bigger depth than the one of the network/live queue.
            depth=live_queue.depth * 8,
            cam_count=live_queue.camera_count,
            frames_per_camera=live_queue.frames_per_camera,
            shape=live_queue.shape,
            name="offline_q",
            mp_ctx=get_mp_ctx(),
        )

        self._pose_process = PoseProcess(
            live_queue,
            self._offline_queue,
            data_queue=self._data_queue,
            cmd_queue=self._inference_cmd_queue,
            msg_queue=self._msg_queue,
            model_location=self._model_location,
        )

        self._pose_process.start()

        return True

    def stop(self):
        if self._status in {InferenceStatus.stopped, InferenceStatus.stopping}:
            return
        logger.debug("stopping..")
        proc = self._pose_process
        self._set_status(InferenceStatus.stopping)
        if proc is not None:
            self._send_message(InferenceCommandMessageKind.Terminate)

            logger.debug(f"<pellet> waiting for process termination")

            t_timeout_sigint = time.perf_counter() + 30
            t_timeout_sigterm = time.perf_counter() + 60
            while True:
                perf_c = time.perf_counter()
                if perf_c > t_timeout_sigterm:
                    logger.warning("sending SIGTERM to %s", proc)
                    # proc.terminate()
                    os.kill(proc.pid, signal.SIGTERM)
                    break
                if perf_c > t_timeout_sigint:
                    t_timeout_sigint += 10
                    logger.warning("sending SIGINT to %s", proc)
                    os.kill(proc.pid, signal.SIGINT)
                if not proc.is_alive():
                    break
                time.sleep(0.1)
            proc.join()
            logger.info("<pellet> process exited with %s", proc.exitcode)
            self._pose_process = None

            self._set_status(InferenceStatus.stopped)

            clear_queue(self._data_queue)
            clear_queue(self._msg_queue)
            clear_queue(self._inference_cmd_queue)
            clear_queue(self._data_monitor_cmd_queue)

        pool = self._process_pool
        if pool is not None:
            logger.verbose("Terminating process pool %s", pool)
            pool.close()
            pool.terminate()
            pool.join()
            logger.verbose("process pool joined and terminated %s", pool)
            self._process_pool = None

        thread = self._offline_thread
        if thread is not None:
            thread.join(3)

        # always:
        self._intersession_block = None
        self._offline_thread = None
        self._intersession_detection = None

    def terminate(self):
        logger.debug("terminating..")
        self.stop()
        data_proc = self._data_monitor_proc
        data_monitor_cmd_queue = self._data_monitor_cmd_queue
        if data_proc is not None:
            logger.debug("joining data_monitor_proc")
            data_monitor_cmd_queue.put(None)
            data_proc.join(3)
            if data_proc.exitcode is None:
                os.kill(data_proc.pid, signal.SIGINT)
                data_proc.join(3)
                if data_proc.exitcode is None:
                    data_proc.terminate()
                    data_proc.join(2)
                    if data_proc.exitcode is None:
                        data_proc.kill()
                        data_proc.join(5)
            logger.verbose("joined %s ; exit_code=%s", data_proc, data_proc.exitcode)

        msg_thread = self._msg_thread
        msg_queue = self._msg_queue
        if msg_thread is not None:
            msg_queue.put(None)
            logger.debug("joining msg_thread")
            msg_thread.join()
            self._msg_thread = None

        logger.verbose("closing mp queues")
        for mp_q in (data_monitor_cmd_queue, self._data_queue, self._inference_cmd_queue, msg_queue):
            if mp_q is not None:
                clear_queue(mp_q, log_dumped=True)
                logger.debug("closing %s size=%s", mp_q, mp_q.qsize())
                mp_q.close()

    def load_configuration(self, configuration: InferenceConfiguration):
        self.model_location = configuration.pose_model_location
        self.is_enabled = configuration.is_enabled
        self.intersession_wait_time = configuration.intersession_wait_time

    def save_configuration(self) -> InferenceConfiguration:
        return InferenceConfiguration(
            pose_model_location=self.model_location,
            is_enabled=self.is_enabled,
            intersession_wait_time=self.intersession_wait_time
        )

    def _set_status(self, status: InferenceStatus):
        self._status = self._on_property_changed(self.STATUS, status, self._status)

    def _send_message(self, kind: InferenceCommandMessageKind, context: typing.Any = None):
        cmd_queue = self._inference_cmd_queue
        # logger.debug("sending command msg %s qsize=%s", kind, cmd_queue.qsize())
        cmd_queue.put((kind, context))
        logger.debug("sent command msg %s qsize=%s", kind, cmd_queue.qsize())

    def _handle_monitor_data_proc_msg(self, msg, ctx):
        args, kwargs = ctx
        if msg is InferenceMonitorDataProc.Msg.POSE_RESULT_READY:
            response = args[0]
            for pair_key, pair_handler in self._pair_offsets_2_handler.items():
                part1, part2 = pair_key
                prev = self._parts_offsets.get(pair_key, None)
                cur = response.get_parts_3d_offset(part1, part2)
                self._parts_offsets[pair_key] = cur
                try:
                    if prev != cur:
                        # if we wanted as "global" property event handling:
                        # self._on_property_changed(f"parts_offset_{part1}_{part2}", cur, prev)
                        pair_handler(cur)
                except Exception as err:
                    logger.exception("offset_changed event callback failed: %s", err)
            try:
                self.pose_response_ready(response)
            except Exception as err:
                logger.exception("pose_response_ready event callback failed: %s", err)

        elif msg is InferenceMonitorDataProc.Msg.INTERSESSION_RESULT_READY:
            ib = self._intersession_block
            if ib is None:
                logger.critical("Got %s but intersession_block is None ; args=%s", msg, args)
            else:
                session_nr, success = args
                ib.configuration.complete(ib.configuration.nonce, success)
                self._intersession_block = None

    def _monitor_msg_queue(self):
        while True:
            try:
                raw = self._msg_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if raw is None:
                break
            msg, context = raw
            try:
                if isinstance(msg, InferenceMonitorDataProc.Msg):
                    self._handle_monitor_data_proc_msg(msg, context)
                    continue
                logger.debug("Processing msg %s ...", msg)
                if msg == InferenceStatusMessageKind.Initialized:
                    self._set_status(InferenceStatus.waiting)
                    pose_algo = self._algorithm
                    pose_algo.initialize(context)
                    # NB: we create a copy of the pose_algo,
                    # because with registered events callback to other objects,
                    # the current one cannot be pickled/serialized with them.
                    # could/should be TODO: implement serialize in PoseAlgo which only include the config/params
                    new_pose_algo = PoseAlgorithm(
                        stereo_params=pose_algo.stereo_params,
                        calib_metadata=pose_algo.calib_metadata,
                        cam_names=pose_algo.cam_names,
                        square_size=pose_algo.square_size,
                        cam_offsets=pose_algo.cam_offsets,
                    )
                    new_pose_algo.initialize(context)
                    self._data_monitor_cmd_queue.put(
                        (InferenceMonitorDataProc.Msg.SET_POSE_ALGO, (new_pose_algo,), None))
                    self._send_message(InferenceCommandMessageKind.Start)
                    self.algo_initialised(self._algorithm)
                elif msg == InferenceStatusMessageKind.Loading:
                    self._set_status(InferenceStatus.loading)
                elif msg == InferenceStatusMessageKind.Performance:
                    logger.info(f"{context :.1f} predict calls/s")
                    fps = context * self._frames_per_camera
                    logger.info(f"{fps :.1f} frames/camera/s ({(fps * 2):.1f} total frames/s)")
                elif msg == InferenceStatusMessageKind.Running:
                    mode = InferenceMode(context)
                    logger.info(f"predict running with {mode.name} queue")
                    if mode == InferenceMode.Live:
                        self._set_status(InferenceStatus.live)
                    else:
                        self._set_status(InferenceStatus.intersession)
                elif msg in {
                    InferenceStatusMessageKind.Created,
                    InferenceStatusMessageKind.Terminated,
                }:
                    # no-op handler
                    pass
                else:
                    logger.warning("Unhandled msg: %s", msg)
            except Exception as err:
                logger.exception("Error processing msg %s: %s", msg, err)

    def _feed_intersession_analysis(self, intersession_block: IntersessionBlock):
        # NB: feed intersession analysis (thread) has currently no way of being "interrupted/stopped",
        # if pose process goes away (when exit) then this will hang up to timeout: currently 15s,
        # see _put_intersession_frame().
        try:
            self.__feed_intersession_analysis(intersession_block)
        except Exception as err:
            logger.exception("_feed_intersession_analysis: error: %s", err)
            EventManager.default().post_event_content(ApiEventKind.intersessionSegmentationError, context=str(err))
            got_error = err
            # do not use anymore InferenceCommandMessageKind.ProcessLive
            # self._send_message(InferenceCommandMessageKind.ProcessLive)
            # intersession_block.configuration.complete(intersession_block.configuration.nonce, False)
            # given we send EOF_OFFLINE_PROCESSING in the following finally clause,
            # the callback is will be done by the monitor data thread instead.
        else:
            got_error = None

        #
        if got_error is not None or self._status not in {InferenceStatus.live, InferenceStatus.intersession}:
            logger.error(f"feed_intersession_analysis stopped given error=%s status=%s", got_error, self._status)
            intersession_block.configuration.complete(intersession_block.configuration.nonce, False)
            self._intersession_block = None
            return
        #
        # in any case sleep a bit to allow pose process to finishes consume:
        offline_q = self._offline_queue
        empty_frame = numpy.zeros((self._frame_height, self._frame_width), dtype=numpy.uint8)
        # NO:
        # eventual pad current batch of each cam:
        # offline_q.pad_to_batch_size(empty_frame)
        # the main feed loop already ensures same nbr of frames is sent for each cam.
        # also post a EOF_OFFLINE_PROCESSING or SWITCH_TO_ONLINE to notify pose process
        # when it has reached end of offline processing:
        offline_q.put_frame_index_category(
            empty_frame,
            FrameIndexCategory.EOF_OFFLINE_PROCESSING if got_error is None
            else FrameIndexCategory.SWITCH_TO_ONLINE,
        )
        # in turn the data monitor thread will detect that as well (via a None sentinel in the data queue),
        # and close its open file handles.

        logger.info("feed intersession finished. intersession_block=%s", intersession_block)
        # DO NOT:
        # self._intersession_block = None
        # it is/must be done by monitor data thread

    def __feed_intersession_analysis(self, intersession_block: IntersessionBlock):
        offline_q = self._offline_queue
        cams = (self._project.camera_1, self._project.camera_2)
        n_cams = len(cams)
        project = self._project.to_local_value()  # get local ref, so to be sure shared values are not modified after
        detection_cfg = intersession_block.configuration
        # and use detections_cfg index & when :
        project.session = detection_cfg.session_index
        project.when = detection_cfg.session_when
        cams_paths = [
            tuple(map(Path, project.get_video_path(name=cam, allow_overwrite=True)))
            for cam in cams
        ]
        tot_skipped_frames = 0
        empty_frame = numpy.zeros((self._frame_height, self._frame_width), dtype=numpy.uint8)
        correct_inference_status = {InferenceStatus.live, InferenceStatus.intersession}
        def check_correct_status():
            cur_status = self._status
            if cur_status not in correct_inference_status:
                raise RuntimeError(f"not correct status: {cur_status}")
        #
        perf_timeout = time.perf_counter() + 15  # intersession_wait_time is too small
        # the pose process and data monitor thread have some delay between them,
        # sometimes up to several seconds (4-5).
        # wait that we get the event from monitor data queue closing its write side to live files:
        logger.debug("waiting stop_recorded on %s", self._data_monitor_proc.stop_recorded)
        while not self._data_monitor_proc.stop_recorded.wait(1):
            if time.perf_counter() > perf_timeout:
                raise RuntimeError("timeout waiting for intersession stop_recorded event")
            check_correct_status()
        self._data_monitor_proc.stop_recorded.clear()
        logger.notice("got stop_recorded")

        # NB: we are not waiting for the capture threads to close their writing side to the video file(s)
        # so this small sleep, for them to get more chance to do it:
        # time.sleep(0.5)
        # This is to not get "moov-atom-not-found" in stderr output from opencv library.
        # NB: not anymore necessary since also controlling pose process + data_monitor with frames indices commands.
        captures_d = {}
        videos_frame_count: Dict[int, int] = {}
        video_paths = [cams_paths[cdx][0] for cdx in range(n_cams)]
        logger.verbose("checking can open video files %s", video_paths)
        while True:
            check_correct_status()

            for cdx, cam in enumerate(cams):
                if cdx not in captures_d:
                    capture, frame_count = check_frame_count(video_paths[cdx])
                    if capture is not None:
                        captures_d[cdx] = capture
                        videos_frame_count[cdx] = frame_count
            if len(captures_d) >= n_cams:
                break
            if time.perf_counter() > perf_timeout:
                EventManager.default().post_event_content(ApiEventKind.intersessionSegmentationInputError)
                raise RuntimeError(f"timeout waiting for intersession video files {video_paths}, trying continue anyway")

            time.sleep(0.1)  # overkill to immediately retry

        captures: List[cv2.VideoCapture] = [captures_d[cdx] for cdx in range(len(cams))]
        cams_processed_fhs = [
            (None if not p.exists() or p.stat().st_size == 0 else p.open())
            for _, _, p in cams_paths
        ]

        frame_idx = 0
        cams_sent_frame_count = [0] * n_cams
        cams_frame_idx = [0] * n_cams
        cams_already_processed_cur_ix = [0] * n_cams
        cams_already_processed_idx_list: List[List[int]] = [
            [] if fh is None else [ int(val.strip()) for val in fh.readlines()]
            for fh in cams_processed_fhs
        ]
        if __debug__ and _local_do_debug:
            cams_already_processed_idx2 = [
                [
                    l[2][0]  # the third row contains the associated frame index in h5 file ([0] to extract it from array)
                    for l in h5py.File(
                        project.get_intersession_pose_path(cam, allow_overwrite=True, suffix="_live")
                    )["df_with_missing"]["table"]
                ]
                for cdx, cam in enumerate(cams)
            ]
            if cams_already_processed_idx_list != cams_already_processed_idx2:
                raise RuntimeError("Unexpected difference in processed cams frames index vs processed h5")

        # NB: tot_frames_to_process:
        # not sure which one to use:
        # 1>
        # tot_frames_to_process = int(frames_per_cam * (
        #         min(videos_frame_count[cdx] - len(cams_already_processed_idx[cdx])
        #             for cdx in range(n_cams)) // frames_per_cam)
        # )
        # 2>
        # tot_frames_to_process = int(((
        #     int(frames_per_cam * (min(videos_frame_count.values()) // frames_per_cam))
        #     - len(cams_already_processed_idx[0])  # should be same for both cams
        # ) // frames_per_cam) * frames_per_cam)
        # 3>
        # tot_frames_to_process = min(videos_frame_count.values()) - min(map(len, cams_already_processed_idx_list))
        # 4>
        tot_frames_to_process = max(videos_frame_count.values()) - min(map(len, cams_already_processed_idx_list))
        if tot_frames_to_process < 0:
            # was somehow happening when video record was not properly closing *after* getting all data
            logger.warning("detected more in live data than in video files: diff=%s", tot_frames_to_process)
            tot_frames_to_process = max(videos_frame_count.values())
            # raise or not raise ?

        # above must be done before following one:
        # pad the smaller one(s) with negative frame idx
        m = max(map(len, cams_already_processed_idx_list))
        for cdx, cam_indices in enumerate(cams_already_processed_idx_list):
            cams_already_processed_idx_list[cdx] = list(np.concatenate([
                np.asarray(cam_indices),
                np.asarray([FrameIndexCategory.PADDING] * (m - len(cam_indices)))
            ]))
        cams_already_processed_idx = numpy.asarray(cams_already_processed_idx_list)
        logger.debug("tot_frames_to_process=%s first cams_already_processed_idx=%s",
                 tot_frames_to_process, cams_already_processed_idx[:, 0])

        all_read = [False] * n_cams
        frames_idx_sent = [
            [] for _ in range(n_cams)
        ]
        while frame_idx < tot_frames_to_process:
            check_correct_status()

            # skip frames already processed during live:
            for cdx, (fh, cam_capture, cur_ix, cur_cam_indices) in enumerate(zip(
                cams_processed_fhs, captures, cams_already_processed_cur_ix, cams_already_processed_idx,
            )):
                if fh is None:
                    continue
                skipped = 0
                while cur_ix < len(cur_cam_indices) and cams_frame_idx[cdx] == cur_cam_indices[cur_ix]:
                    skipped += 1
                    cur_ix += 1
                    cams_frame_idx[cdx] += 1
                    ret, _ = cam_capture.read()
                    if not ret:
                        all_read[cdx] = True
                        break

                cams_already_processed_cur_ix[cdx] = cur_ix
                if skipped > 0:
                    logger.spam("cam-%s: skipped=%s", cdx, skipped)
                    tot_skipped_frames += skipped

                if all_read[cdx]:
                    self._offline_queue.put_block(empty_frame, cdx, FrameIndexCategory.PADDING)
                else:
                    if not self._put_intersession_frame(cam_capture, cdx, cams_frame_idx[cdx]):
                        all_read[cdx] = True
                        self._offline_queue.put_block(empty_frame, cdx, FrameIndexCategory.PADDING)
                        # if we prematurely reach the end of the video stream then give a padding instead
                    else:
                        frames_idx_sent[cdx].append(cams_frame_idx[cdx])
                        cams_frame_idx[cdx] += 1
                cams_sent_frame_count[cdx] += 1
            # end for cdx ...
            if all(all_read):
                logger.info("reached end of all video cams: %s ; frame_idx=%s", all_read, frame_idx)
                break

            frame_idx += 1
        # end while frame_idx < tot_frames_to_process

        # need to pad the current batch
        # we've written same nbr of frames to all cams, so can use cams_sent_frame_count[0]
        missing_for_batch = (offline_q.frames_per_camera - cams_sent_frame_count[0] % offline_q.frames_per_camera) % offline_q.frames_per_camera
        for _ in range(missing_for_batch):
            for cdx in range(n_cams):
                offline_q.put_block(empty_frame, cdx, FrameIndexCategory.PADDING)

        if __debug__ and _local_do_debug:
            for cdx in range(n_cams):
                with open(str(cams_paths[cdx][-1]) + "_sent_to_processing.txt", "w") as fh:
                    fh.write("\n".join(map(str, chain(frames_idx_sent[cdx], [""]))))

        # total frame count: taking the min of all saved videos frame count:
        intersession_block.frame_count = min(videos_frame_count.values())

        # ProcessLiveWhenReady is async vs EOF_OFFLINE_PROCESSING just send before
        # it's not anymore actually used by pose process, but we still deliver it, for log purpose mainly.
        self._send_message(InferenceCommandMessageKind.ProcessLiveWhenReady)

        logger.success("passed %s frames per camera frame_count=%s ; "
                       "tot_skipped_frames=%s cams_frame_idx=%s cams_sent_frame_count=%s",
                       frame_idx, intersession_block.frame_count,
                       tot_skipped_frames, cams_frame_idx, cams_sent_frame_count)

    def _put_intersession_frame(self, capture, cam_index: int, frame_idx: int, *, timeout: float = 10) -> bool:
        ret, frame = capture.read()
        if not ret:
            logger.verbose("end of video at index %s", cam_index)
            return False
        if len(numpy.shape(frame)) >= 3:
            frame = frame[:, :, 0]
        self._offline_queue.put_block(frame, cam_index, frame_idx, timeout=timeout, sleep_retry=0.025)
        return True

    def _intersession_process(self, project: ProjectInfo, intersession_detection: IntersessionDetection):
        project = project.to_local_value()  # get local ref to current project infos,
        detection_config = intersession_detection.configuration
        # *** but *** force update with intersession_detection when & session, to be totally sure:
        project.session = detection_config.session_index
        project.when = detection_config.session_when

        try:
            async_res = self._process_pool.apply_async(
                intersession_process,
                args=(project,),
                kwds=dict(calib_dir=self._calib_dir),
            )
            result = async_res.get()
        except Exception as err:
            logger.exception("Error processing intersession: %s", err)
            processed_ok = False
            result = None
        else:
            processed_ok = True

        intersession_detection.configuration.complete(intersession_detection.configuration.nonce, processed_ok)
        # NB: triggering/calling the "complete" of the detection BEFORE trigger the detection_result_ready below,

        if processed_ok:
            self.detection_result_ready(result)
        self._intersession_detection = None
