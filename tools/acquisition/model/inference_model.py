import logging
import math
import multiprocessing
import operator
import os
import queue
import signal
import threading
import time
import typing
from itertools import chain
from pathlib import Path
from statistics import mean
from typing import Optional, Union, List, Dict, TextIO, Tuple
from dataclasses import dataclass
from enum import Enum
from threading import Thread

import cv2
import h5py
import numpy
import numpy as np
import pandas

from autotrainer.core import FixedArrayMultiQueue, ObservableObject, ProjectInfo, EventManager, clear_queue, \
    InferenceConfiguration, Offset3DTuple
from autotrainer.core.fixed_array_queue import BufferResult
from autotrainer.core.logging import get_verbose_logger
from autotrainer.behavior import SegmentationConfiguration, DetectionConfiguration, intersession_inference, \
    intersession_process, BehaviorEventKind, InferenceProtocol
from autotrainer.core.message import FrameIndexCategory
from autotrainer.core.multiproc import get_mp_ctx
from autotrainer.inference import PoseProcess, InferenceCommandMessageKind, InferenceStatusMessageKind, PoseAlgorithm, \
    DlcPoseModel, MemoryPoseModel, InferenceMode, PoseResponse
from autotrainer.inference.pose_elements import SceneElement
from tools.acquisition.model.project_dependent_protocol import ProjectDependentProtol

logger = get_verbose_logger(__name__)


# even better is to use __debug__ and use "python -O ..."
# see https://docs.python.org/3/using/cmdline.html#cmdoption-O
_local_do_debug = False


def _shorten_text_file(lines: List[str], path: Path, limit: int):
    with path.open("w") as fh:
        fh.write("\n".join(chain(lines[:limit], [''])))

def _short_vid_file(path: Path, limit: int):
    "ffmpeg -sseof -2 -i input.mp4 output.mp4"
    cap = cv2.VideoCapture(path.as_posix())
    idx = 0
    ret, frame = cap.read()
    if not ret:
        return
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*'mp4v'), fps, (w, h))
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        writer.write(frame)
        idx += 1
        if idx >= limit:
            break
    writer.release()
    cap.release()


def _close_fhs(cams_frame_idx_fhs: Optional[List[Optional[TextIO]]]):
    if cams_frame_idx_fhs is None:
        return
    cnt_closed = 0
    for idx, fh in enumerate(cams_frame_idx_fhs):
        if fh is not None:
            cnt_closed += 1
            logger.debug("closing %s", fh.name)
            fh.flush()
            fh.close()
            cams_frame_idx_fhs[idx] = None
    if cnt_closed > 0:
        logger.debug("closed %s fhs", cnt_closed)


def _close_h5(fhs: List[Optional[h5py.File]]):
    for idx, fh in enumerate(fhs or []):
        if fh is not None:
            logger.info("exiting %s", fh.name)
            # fh.flush()
            fh.__exit__(None, None, None)
            fh.close()
            fhs[idx] = None

def check_frame_count(file_path: Path):
    capture = cv2.VideoCapture(file_path.as_posix())
    count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if count < 1:
        capture.release()
        return None, None
    logger.verbose("Opened %s: tot_frames=%s size=%s", file_path.name, count, file_path.stat().st_size)
    return capture, count


def open_h5_file(file_path: Path):
    datasets = h5py.File(file_path)["df_with_missing"]["table"]
    logger.debug("%s: %s entries", file_path, len(datasets))
    return datasets


class InferenceStatus(str, Enum):
    stopped = "Stopped"
    loading = "Loading"
    waiting = "Waiting"
    live = "Live"
    intersession = "Intersession"
    stopping = "Stopping"


@dataclass
class IntersessionBlock:
    configuration: SegmentationConfiguration
    frame_count: int = 0
    parts_count: int = 10
    pose_data: numpy.ndarray = None
    pose_data_list: List[List[numpy.ndarray]] = None
    pose_data_dict: List[Dict[int, numpy.ndarray]] = None

    def __post_init__(self):
        self.pose_data = numpy.empty((0, self.parts_count * 3), dtype=numpy.float32)
        self.pose_data_list = []
        self.pose_data_dict = []


@dataclass
class IntersessionDetection:
    configuration: DetectionConfiguration


class InferenceModel(ObservableObject, InferenceProtocol, ProjectDependentProtol):

    def __init__(self,
        pose_algorithm: PoseAlgorithm,
    ):
        super().__init__(event_names=(
            'pose_response_ready',
            'detection_result_ready',
            'diamond_triangle_offset_changed',
            'star_triangle_offset_changed',
            'algo_initialised',
        ))

        mp_ctx = get_mp_ctx()
        self._data_queue = mp_ctx.Queue(maxsize=4096)
        self._cmd_queue = mp_ctx.Queue(maxsize=64)
        self._msg_queue = mp_ctx.Queue(maxsize=64)

        self._offline_queue: Optional[FixedArrayMultiQueue] = None
        self._offline_thread: Optional[Thread] = None

        self._is_enabled = False
        self._model_location = ""
        self._algorithm = pose_algorithm
        # self._algorithm.pose_changed += self._pose_changed
        # no need, we have the pose response in the monitor data queue function

        self._msg_thread = None
        self._data_thread = None

        self._process: Optional[PoseProcess] = None
        self._is_running = True
        self._is_predict_enabled = True
        self._status = InferenceStatus.stopped

        self._frames_per_camera = 0
        self._frame_width = 1
        self._frame_height = 1

        self._intersession_wait_time: float = 1.0

        self._project: Optional[ProjectInfo] = None
        self._intersession_block: Optional[IntersessionBlock] = None
        self._intersession_detection: Optional[IntersessionDetection] = None
        self._stop_recorded = threading.Event()
        self._recording_live_batch = 64
        self._monitored_parts_offsets = [
            (SceneElement.Diamond, SceneElement.Triangle),
            (SceneElement.Star, SceneElement.Triangle),
        ]
        self._parts_offsets: Dict[Tuple[SceneElement, SceneElement], Offset3DTuple] = {}

    @property
    def project(self) -> ProjectInfo:
        return self._project

    @project.setter
    def project(self, value: ProjectInfo) -> None:
        self._project = value

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

    def get_parts_offsets(self, part1: str, part2: str) -> Optional[Offset3DTuple]:
        """Return the offsets of part2 relative to part1 as last known"""
        part1 = SceneElement(part1).value
        part2 = SceneElement(part2).value
        v_offsets = self._parts_offsets.get((part1, part2), None)
        if v_offsets is None:
            v_offsets = self._parts_offsets.get((part2, part1), None)
            if v_offsets is None:
                return None
            v_offsets = tuple(map(operator.neg, v_offsets))
        return Offset3DTuple(v_offsets)

    def _check_previous_offline_thread(self):
        cur_off = self._offline_thread
        if cur_off is not None:
            # protection, if we need more than 1 executing thread at the same time then we need a list to retain the
            # threads instead of only one of them.
            if cur_off.is_alive():
                logger.warning("Previous offline thread still alive: %s, join might block ~long", cur_off)
            cur_off.join()
            self._offline_thread = None

    def perform_segmentation(self, configuration: SegmentationConfiguration):
        logger.info("performing segmentation")
        self._check_previous_offline_thread()
        self._intersession_block = IntersessionBlock(configuration=configuration,
                                                     parts_count=self._algorithm.part_count)
        for _ in range(self._offline_queue.camera_count):
            self._intersession_block.pose_data_list.append([])
            self._intersession_block.pose_data_dict.append({})

        self._send_message(InferenceCommandMessageKind.ProcessOffline)
        # ProcessOffline is not anymore used.
        # the trigger for pose process to switch to offline queue processing is now delivered by
        # camera capture itself, which send an EOF_RECORDING when a video/session record finishes.

        # once the message is sent, also wait a bit,
        # this is to give some time to inference process to switch to offline queue,
        # and also reset its offline read queue side:
        # time.sleep(0.5)
        # Not anymore needed, see video_capture and below __feed_intersession_analysis.
        self._offline_thread = Thread(target=self._feed_intersession_analysis, name="feed_intersession_analysis")
        # but then, wait again a bit of more time.
        # this is to give some time to the monitor data queue thread, to get/detect the end of recording in progress,
        # and switch to offline processing request (which is coming indirectly from the pose process),
        # and get a chance to close the "h5-live" and frames-idx-already-processed file handles.
        # time.sleep(0.5)
        # NB: this might not be enough though, we probably should use a threading event (with a timeout eventually)
        # Now using thread event.
        self._offline_thread.start()

    def perform_detection(self, configuration: DetectionConfiguration):
        logger.info("performing detection analysis")
        self._check_previous_offline_thread()
        self._intersession_detection = IntersessionDetection(configuration)
        self._offline_thread = Thread(target=self._intersession_process, name="intersession_process")
        self._offline_thread.start()

    def perform_live(self):
        self.set_inference_to_online()

    def set_inference_to_online(self):
        offline_queue = self._offline_queue
        if offline_queue is not None:
            logger.notice("Setting inference back to online with SWITCH_TO_ONLINE")
            empty = numpy.zeros(offline_queue.shape, dtype=numpy.uint8)
            self._offline_queue.put_frame_index_category(empty, FrameIndexCategory.SWITCH_TO_ONLINE)

    def start(self, network_queue: FixedArrayMultiQueue) -> bool:
        if self._msg_thread is None:
            self._msg_thread = Thread(target=self._monitor_msg_queue, name="monitor_msg_queue")
            self._msg_thread.start()

        if self._data_thread is None:
            self._data_thread = Thread(target=self._monitor_data_queue, name="monitor_data_queue")
            self._data_thread.start()

        if network_queue is None:
            logger.warning("pellet not started because there is no pellet image queue")
            self._set_status(InferenceStatus.stopped)
            return False

        self._frame_height, self._frame_width = network_queue.shape
        self._frames_per_camera = network_queue.frames_per_camera

        self._offline_queue = FixedArrayMultiQueue(
            # offline queue can have a bigger depth than the one of the network/live queue.
            depth=network_queue.depth * 8,
            cam_count=network_queue.camera_count,
            frames_per_camera=network_queue.frames_per_camera,
            shape=network_queue.shape,
            name="offline_q",
            mp_ctx=get_mp_ctx(),
        )

        if self._model_location is None or len(self._model_location) == 0:
            logger.warning("pellet model not specified; using in-memory random data")
            model = MemoryPoseModel(network_queue.batch_size)
        else:
            model = DlcPoseModel(self._model_location, 1, 0, network_queue.batch_size)

        if not model.is_valid():
            logger.warning("pellet not started because the model does not exist at the specified location")
            return False

        self._process = PoseProcess(
            model,
            network_queue,
            self._offline_queue,
            data_queue=self._data_queue,
            cmd_queue=self._cmd_queue,
            msg_queue=self._msg_queue,
        )

        self._process.start()

        return True

    def stop(self):
        proc = self._process
        if proc is not None:
            self._set_status(InferenceStatus.stopping)
            self._send_message(InferenceCommandMessageKind.Terminate)

            logger.debug(f"<pellet> waiting for process termination")

            t_timeout_sigint = time.time() + 30
            t_timeout_sigterm = time.time() + 60
            while True:
                t = time.time()
                if t > t_timeout_sigterm:
                    logger.warning("sending SIGTERM to %s", proc)
                    # proc.terminate()
                    os.kill(proc.pid, signal.SIGTERM)
                    break
                if t > t_timeout_sigint:
                    t_timeout_sigint += 10
                    logger.warning("sending SIGINT to %s", proc)
                    os.kill(proc.pid, signal.SIGINT)
                if not proc.is_alive():
                    break
                time.sleep(0.1)
            proc.join()
            logger.info("<pellet> process exited with %s", proc.exitcode)
            self._process = None

            self._set_status(InferenceStatus.stopped)

            clear_queue(self._data_queue)
            clear_queue(self._msg_queue)
            clear_queue(self._cmd_queue)

    def terminate(self):
        self.stop()
        self._is_running = False
        data_thread = self._data_thread
        if data_thread is not None:
            logger.verbose("joining data_thread")
            data_thread.join()
            self._data_thread = None
        msg_thread = self._msg_thread
        if msg_thread is not None:
            logger.verbose("joining msg_thread")
            msg_thread.join()
            self._msg_thread.join()

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
        self._status = self._on_property_changed("status", status, self._status)

    def _send_message(self, kind: InferenceCommandMessageKind, context: typing.Any = None):
        cmd_queue = self._cmd_queue
        # logger.debug("sending command msg %s qsize=%s", kind, cmd_queue.qsize())
        cmd_queue.put((kind, context))
        logger.debug("sent command msg %s qsize=%s", kind, cmd_queue.qsize())

    def _monitor_msg_queue(self):
        while self._is_running:
            try:
                msg, context = self._msg_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            logger.debug("Processing msg %s ...", msg)
            try:
                if msg == InferenceStatusMessageKind.Initialized:
                    self._set_status(InferenceStatus.waiting)
                    self._algorithm.initialize(context)
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
                else:
                    logger.warning("Unhandled msg: %s", msg)
            except Exception as err:
                logger.exception("Error processing msg %s: %s", msg, err)

    def _monitor_data_queue(self):
        cams = [self.project.camera_1, self.project.camera_2]
        n_cams = len(cams)
        range_cams = range(n_cams)
        cams_frame_idx_fhs = None
        pose_paths: List[Path] = []
        axis_labels = ("x", "y", "likelihood")
        cams_read_h5_dss: List[h5py.Dataset] = []
        cams_read_h5_idx: List[int] = []
        recording_in_progress = False
        next_prev_mode = None
        prev_session = None
        tot_written_to_live = None
        t_log_counters = time.time()
        cnt_data_received = 0

        writes_h5_live_durations = []
        cur_h5_live_batch = [[] for _ in range_cams]
        cur_cams_indices = [[] for _ in range_cams]
        tot_skipped = 0

        t_start_offline = 0

        while self._is_running:

            t_now = time.time()
            if t_now > t_log_counters:
                t_log_counters = t_now + 5
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("status=%s data=%s avg_writes_h5_live=%.6f skipped_h5_live=%s",
                                self._status, cnt_data_received,
                                0 if len(writes_h5_live_durations) == 0 else mean(writes_h5_live_durations),
                                 tot_skipped)
                cnt_data_received = 0
                tot_skipped = 0
                writes_h5_live_durations.clear()

            prev_mode = next_prev_mode  # don't forget
            try:
                (pose_data, mode, frames_indices) = self._data_queue.get_nowait()
            except queue.Empty:
                time.sleep(0.005)
                continue
            next_prev_mode = mode

            pose_data: Optional[List[numpy.ndarray]]
            frames_indices: Optional[numpy.ndarray]

            if recording_in_progress:  # and cams_frame_idx_fhs is not None:
                # thx to feed analysis which send a full SWITCH_TO_OFFLINE_MODE batch frames indices,
                # this condition allows to know when to close/stopping writing to live files,
                # and reopen for offline mode
                if frames_indices is None or numpy.isin(
                    frames_indices[:, -1], [
                        FrameIndexCategory.SWITCH_TO_OFFLINE_MODE,
                        FrameIndexCategory.SWITCH_TO_ONLINE,
                        FrameIndexCategory.ONLINE_NO_RECORDING,
                    ],
                ).any():
                    recording_in_progress = False
                    # t_start_offline = time.time()
                    logger.notice("Detected stop of recording in progress ; status=%s ; mode=%s prev=%s frames_indices=%s",
                                  self._status, mode, prev_mode, frames_indices)

                    for cdx, cam_pose_path, cur_cam_indices, cur_h5_live in zip(range_cams, pose_paths, cur_cams_indices, cur_h5_live_batch):
                        if len(cur_h5_live) == 0:
                            continue
                        cur = [a for a in cur_h5_live if len(a) > 0]  # if not necessary when correctly filtered ahead
                        cur = numpy.vstack(cur)
                        indices = list(range(cur.shape[0]))
                        df_xyp = pandas.DataFrame(cur, columns=self._algorithm.pose_result_columns, index=indices)
                        df_xyp["frame_idx"] = list(cur_cam_indices)  # also store the frame idx with the results
                        logger.debug("flushing remaining h5 batch (%s) to %s",
                                     len(df_xyp), cam_pose_path)
                        df_xyp.to_hdf(cam_pose_path,
                                      "df_with_missing",
                                      format="table",
                                      mode="a",
                                      append=True,  # required as well for really concat
                                      )
                        cur_h5_live.clear()
                        cur_cam_indices.clear()
                    #
                    _close_fhs(cams_frame_idx_fhs)
                    cams_frame_idx_fhs = None
                    self._stop_recorded.set()

            cnt_data_received += 1

            prj = self.project
            ib: Optional[IntersessionBlock] = self._intersession_block
            try:
                if prev_mode != mode:
                    logger.verbose("Detected inference mode change -> %s frames=%s", mode, frames_indices)

                if (
                    not recording_in_progress
                    and pose_data is not None
                    # and self._status == InferenceStatus.live
                    and mode == InferenceMode.Live
                    and frames_indices is not None
                    and (frames_indices >= 0).any()
                    and prj.session.value != prev_session  # REQUIRED
                ):
                    self._stop_recorded.clear()  # reset the flag at start of new record,
                    # it will be used at end of record, to signal feed analysis thread that we closed the live files.

                    tot_written_to_live = 0
                    recording_in_progress = True
                    prev_session = prj.session.value
                    logger.verbose("Detected new record in progress ; status=%s mode=%s frames indices: %s",
                                   self._status, mode, frames_indices)
                    cams_frame_idx_fhs = []
                    pose_paths = []
                    for cam in cams:
                        _, _, p_indices = prj.get_video_path(cam, allow_overwrite=True)
                        cams_frame_idx_fhs.append(Path(p_indices).open("w"))
                        pose_path = Path(prj.get_intersession_pose_path(cam, allow_overwrite=True, suffix="_live"))
                        pose_paths.append(pose_path)

                if mode == InferenceMode.Live:
                    if recording_in_progress:  # and cams_frame_idx_fhs is not None and frames_indices is not None:
                        tot_written_to_live += 1
                        for fh, cam_fr_indices in zip(cams_frame_idx_fhs, frames_indices):
                            cam_fr_indices = list(filter(lambda i: i >= 0, cam_fr_indices))
                            if fh is not None and len(cam_fr_indices) > 0:
                                fh.write("\n".join(map(str, chain(cam_fr_indices, [""]))))
                                fh.flush()
                        for cdx, (cam_fr_indices, cam_pose_path, cam_h5_live, cam_indices) in enumerate(
                            zip(frames_indices, pose_paths, cur_h5_live_batch, cur_cams_indices)
                        ):
                            # reminder: pose_data has 1 frame cam1, 1 frame cam2, 1 frame cam1, etc..
                            t0 = time.time()
                            cur = pose_data[cdx::n_cams]
                            cur = {
                                fx: f.flatten()
                                for fx, f in zip(cam_fr_indices, cur)
                                if fx >= 0
                            }
                            cur = [cur[ix] for ix in sorted(cur)]
                            if len(cur) == 0:
                                continue
                            cam_h5_live.append(cur)
                            cam_indices.extend(filter(lambda ix: ix >= 0, cam_fr_indices))
                            t1 = time.time()
                            writes_h5_live_durations.append(t1 - t0)
                            if len(cam_h5_live) >= self._recording_live_batch:
                                t0 = time.time()
                                cur = numpy.vstack(cam_h5_live)
                                indices = list(range(cur.shape[0]))
                                df_xyp = pandas.DataFrame(cur,
                                                          columns=self._algorithm.pose_result_columns, index=indices)
                                df_xyp["frame_idx"] = list(cam_indices)  # also store the frame idx with the results
                                df_xyp.to_hdf(cam_pose_path,
                                              "df_with_missing",
                                              format="table",
                                              mode="a",
                                              append=True,  # required as well for really concat
                                )
                                t1 = time.time()
                                writes_h5_live_durations.append((t1 - t0) / self._recording_live_batch)
                                cam_h5_live.clear()
                                cam_indices.clear()
                            # pose_fhs[cdx]...

                    new_pose_data = []
                    got_done = False
                    for fx in range(self._frames_per_camera):
                        for cdx, cam_fr_indices in zip(range_cams, frames_indices):
                            ix = fx * n_cams + cdx
                            if cam_fr_indices[fx] < FrameIndexCategory.ONLINE_NO_RECORDING:
                                new_pose_data = new_pose_data[:fx * n_cams]
                                got_done = True
                                break
                            new_pose_data.append(pose_data[ix])
                        if got_done:
                            break

                    r = len(pose_data) % n_cams
                    if r != 0 or len(pose_data) == 0:
                        new_pose_data = pose_data[:-r]
                        if len(new_pose_data) == 0:
                            logger.warning("skipping invalid nbr of pose_data: %s ; frame_indices=%s",
                                           len(pose_data), frames_indices)
                            continue
                        pose_data = new_pose_data
                    #
                    response = self._algorithm.process(pose_data, pairs_3d_offsets=self._monitored_parts_offsets)
                    #
                    for part1, part2 in self._monitored_parts_offsets:
                        pair_key = (part1, part2)
                        prev = self._parts_offsets.get(pair_key, None)
                        cur = response.get_parts_3d_offset(part1, part2)
                        self._parts_offsets[pair_key] = cur
                        if prev != cur:
                            # if we wanted as "global" property event handling:
                            # self._on_property_changed(f"parts_offset_{part1}_{part2}", cur, prev)
                            if pair_key == (SceneElement.Diamond, SceneElement.Triangle):
                                self.diamond_triangle_offset_changed(cur)
                            elif pair_key == (SceneElement.Star, SceneElement.Triangle):
                                self.star_triangle_offset_changed(cur)
                    self.pose_response_ready(response)

                elif mode == InferenceMode.Offline:

                    if frames_indices is not None and numpy.isin(frames_indices[:, -1], [
                        FrameIndexCategory.SWITCH_TO_ONLINE,
                        FrameIndexCategory.ONLINE_NO_RECORDING,
                    ]).any():   # .all():
                        continue

                    if (  # prev_mode == InferenceMode.Live and
                        len(cams_read_h5_dss) == 0
                        # and frames_indices is not None and (frames_indices >= 0).any()
                        # with random cam there might be no frame to replay, so we get immediatelly all < 0
                    ):
                        t_start_offline = time.time()
                        logger.notice("Opening live files for offline processing ; prev_mode=%s frames=%s",
                                      prev_mode, frames_indices)
                        cams_read_h5_dss = [
                            open_h5_file(cam_pose_path)
                            for cam_pose_path in pose_paths
                        ]
                        cams_read_h5_idx = [0] * n_cams
                        tot_skipped = 0

                    if pose_data is None:
                        # end of intersession replay
                        # we can reset the offline queue here, it's safe :
                        # the pose process has switched to its online queue at this point
                        for cdx in range(self._offline_queue.camera_count):
                            self._offline_queue.reset_writer(cdx)
                        if ib is not None:
                            fill_live_end = True
                            for cdx, pdl, pdd, cur_h5_idx, cur_h5_dss in zip(
                                range_cams, ib.pose_data_list, ib.pose_data_dict, cams_read_h5_idx, cams_read_h5_dss
                            ):
                                skipped = 0
                                while fill_live_end and cur_h5_idx < len(cur_h5_dss):
                                    ds_row = cur_h5_dss[cur_h5_idx]
                                    pdl.append(ds_row[1])
                                    if _local_do_debug:
                                        pdd[ds_row[2][0]] = ds_row[1]
                                    cur_h5_idx += 1
                                    skipped += 1
                                logger.debug("cam-%s: read %s final entries from h5 live file",
                                             cdx, skipped)
                            try:
                                if _local_do_debug:
                                    diffs = [
                                        set(range(len(ib.pose_data_dict[cdx]))) - set(ib.pose_data_dict[cdx])
                                        for cdx in range(len(cams))
                                    ]
                                    if any(diffs):
                                        logger.warning("seen missing frame indices: %s", diffs)
                                    for cdx, p in enumerate(pose_paths):
                                        with open(str(p) + ".idx_monitor_data_q.txt", "w") as fh:
                                            fh.write("\n".join(chain(map(str, sorted(ib.pose_data_dict[cdx])), [''])))

                                min_nbr_pd = min(map(len, ib.pose_data_list))

                                # current analyse code also require exact same frame number in all cameras,
                                # let's trim what's necessary:
                                for cam in cams:
                                    paths = list(map(Path, prj.get_video_path(cam, allow_overwrite=True)))
                                    ts_file = paths[1]
                                    lines = [v for v in ts_file.read_text().split('\n') if v.strip()]
                                    # not the best way to do this,
                                    # maybe inspecting the video file for total frames is faster.
                                    # we must also have the info somewhere in active memory during this run/session
                                    if len(lines) > min_nbr_pd:
                                        logger.warning("%s: trimming raw data to %s entries", cam, min_nbr_pd)
                                        _shorten_text_file(lines, ts_file, min_nbr_pd)
                                        # normally not necessary:
                                        # _short_vid_file(paths[0], min_nbr_pd)
                                        # _shorten_text_file(paths[2], min_nbr_pd)

                                ib.pose_data = numpy.vstack(
                                    list(chain(
                                        [ib.pose_data],  # supposed the empty init array
                                        (
                                             pdl[ix]
                                             for ix in range(min_nbr_pd)
                                             for pdl in ib.pose_data_list
                                        )
                                    ))
                                )
                                logger.notice("assembled %s pose responses, speed=%.3f/s (vstack=%s)"
                                              " now calling intersession_inference()",
                                              min_nbr_pd, 2 * min_nbr_pd / (time.time() - t_start_offline), ib.pose_data.shape[0])
                                intersession_inference(ib.pose_data, self._algorithm.part_names,
                                                       self._project)
                                success = True
                                logger.success("fully processed session-%s inference with %s total pose responses",
                                               prev_session, ib.pose_data.shape[0])
                            except Exception as err:
                                logger.exception("Error during intersession_inference: %s", err)
                                success = False

                            ib.configuration.complete(ib.configuration.nonce, success)
                            self._intersession_block = None
                            cams_read_h5_dss = []
                            _close_fhs(cams_frame_idx_fhs)

                    elif ib is not None:
                        assert pose_data is not None
                        if (frames_indices < 0).all():
                            # next pose_data we get/read should be None, ending the current offline session
                            logger.debug("got all negative frame indices batch: %s", frames_indices)
                            # this also happens when start of offline data
                            continue
                        # we can now append the received/processed frame data:
                        skipped = 0
                        # append any of the live processed frame data that are before current
                        # received/processed frames indices:
                        for cdx, pdl, cur_h5_dss, pdd, cam_fr_indices in zip(
                            range_cams, ib.pose_data_list, cams_read_h5_dss, ib.pose_data_dict, frames_indices
                        ):
                            cur_h5_ix = cams_read_h5_idx[cdx]
                            for fx, frame in enumerate(pose_data[cdx::len(cams)]):
                                frame_idx = cam_fr_indices[fx]
                                if frame_idx < 0:  # == FrameIndexCategory.PADDING:
                                    logger.debug("cam-%s : fx=%s got negative frame idx: %s", cdx, fx, cam_fr_indices)
                                    continue
                                    # break
                                while cur_h5_ix < len(cur_h5_dss) and frame_idx > cur_h5_dss[cur_h5_ix][2]:
                                    ix = cur_h5_dss[cur_h5_ix][2][0]
                                    f = cur_h5_dss[cur_h5_ix][1]
                                    if _local_do_debug:
                                        if ix != len(pdl) or ix in pdd:
                                            logger.warning(
                                                "cam-%s: detected invalid live frame ix: %s vs %s - double=%s",
                                                cdx, ix, len(pdl), ix in pdd)
                                        pdd[ix] = f
                                    pdl.append(f)
                                    cur_h5_ix += 1
                                    skipped += 1
                                cams_read_h5_idx[cdx] = cur_h5_ix
                                f = frame.flatten()
                                if _local_do_debug:
                                    if (frame_idx != len(pdl) and frame_idx < len(cur_h5_dss)) or frame_idx in pdd:
                                        logger.warning("cam-%s: detected invalid frame idx: %s vs %s - double=%s",
                                                       cdx, frame_idx, len(pdl), frame_idx in pdd)
                                    pdd[frame_idx] = f
                                pdl.append(f)

                        tot_skipped += skipped

                    else:
                        assert ib is None and pose_data is not None
                        if __debug__:
                            logger.warning("invalid state: ib=None but pose_data%s", pose_data)

            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as err:
                logger.exception("_monitor_data_queue: loop error processing mode=%s %s: %s",
                                 mode, type(pose_data), err)

        # end while self._is_running

    def _feed_intersession_analysis(self):
        # NB: feed intersession analysis (thread) has currently no way of being "interrupted/stopped",
        # if pose process goes away (when exit) then this will hang up to timeout: currently 15s,
        # see _put_intersession_frame().
        try:
            self.__feed_intersession_analysis()
        except Exception as err:
            logger.exception("_feed_intersession_analysis: error: %s", err)
            EventManager.default().post_event_content(BehaviorEventKind.intersessionSegmentationError, context=str(err))
            self._send_message(InferenceCommandMessageKind.ProcessLive)
            self._intersession_block.configuration.complete(self._intersession_block.configuration.nonce, False)
            self._intersession_block = None

    def __feed_intersession_analysis(self):
        cams = (self._project.camera_1, self._project.camera_2)
        n_cams = len(cams)
        cur_session_nbr = self._project.session.value
        cams_paths = [
            tuple(map(Path, self._project.get_video_path(name=cam, session=cur_session_nbr, allow_overwrite=True)))
            for cam in cams
        ]
        tot_skipped_frames = 0
        empty_frame = numpy.zeros((self._frame_height, self._frame_width), dtype=numpy.uint8)
        #
        # this allows data_monitor to see/know when to switch to offline mode:
        self._offline_queue.put_frame_index_category(empty_frame, FrameIndexCategory.SWITCH_TO_OFFLINE_MODE)

        timeout = time.time() + 15  # self._intersession_wait_time

        # wait that we get the event from monitor data queue closing its write side to live files:
        logger.debug("waiting stop_recorded")
        while not self._stop_recorded.wait(1):
            if time.time() > timeout:
                raise RuntimeError("timeout waiting for intersession stop_recorded event")
        self._stop_recorded.clear()
        logger.notice("got stop_recorded")

        # NB: we are not waiting for the capture threads to close their writing side to the video file(s)
        # so this small sleep, for them to get more chance to do it:
        # time.sleep(0.5)
        # This is to not get "moov-atom-not-found" in stderr output from opencv library.
        # NB: not anymore necessary since also controlling pose process + data_monitor with frames indices commands.
        captures_d = {}
        videos_frame_count: Dict[int, int] = {}
        while True:
            for cdx, cam in enumerate(cams):
                if cdx not in captures_d:
                    capture, frame_count = check_frame_count(cams_paths[cdx][0])
                    if capture is not None:
                        captures_d[cdx] = capture
                        videos_frame_count[cdx] = frame_count
            if len(captures_d) >= n_cams:
                break
            if time.time() > timeout:
                EventManager.default().post_event_content(BehaviorEventKind.intersessionSegmentationInputError)
                raise RuntimeError("timeout waiting for intersession video files")
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
        if _local_do_debug:
            cams_already_processed_idx2 = [
                [
                    l[2][0]  # the third row contains the associated frame index in h5 file ([0] to extract it from array)
                    for l in h5py.File(
                        self.project.get_intersession_pose_path(cam, session=cur_session_nbr, allow_overwrite=True,
                                                                suffix="_live"))["df_with_missing"]["table"]
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
                    cams_sent_frame_count[cdx] += 1
                    while self._offline_queue.put(empty_frame, cdx, FrameIndexCategory.PADDING,
                                                  allow_overflow=False) != BufferResult.Ok:
                        time.sleep(0.005)
                else:
                    if not self._put_intersession_frame(cam_capture, cdx, cams_frame_idx[cdx]):
                        all_read[cdx] = True
                    else:
                        cams_sent_frame_count[cdx] += 1
                        frames_idx_sent[cdx].append(cams_frame_idx[cdx])
                        cams_frame_idx[cdx] += 1
            # end for cdx ...
            if all(all_read):
                logger.info("reached end of all video cams: %s ; frame_idx=%s", all_read, frame_idx)
                break

            frame_idx += 1
        # end while frame_idx < tot_frames_to_process

        # fill current batch of each cam:
        for cdx in range(n_cams):
            self._offline_queue.pad_cur_batch(cdx, empty_frame)

        if _local_do_debug:
            for cdx in range(n_cams):
                with open(str(cams_paths[cdx][-1]) + "_sent_to_processing.txt", "w") as fh:
                    fh.write("\n".join(map(str, chain(frames_idx_sent[cdx], [""]))))

        # total frame count: taking the min of all saved videos frame count:
        self._intersession_block.frame_count = min(videos_frame_count.values())

        # also post a **full negative indices batch** to notify pose process
        # when it has reached end of offline processing:
        self._offline_queue.put_frame_index_category(empty_frame, FrameIndexCategory.EOF_OFFLINE_PROCESSING)

        # ProcessLiveWhenReady is async vs EOF_OFFLINE_PROCESSING just send before
        # it's not anymore actually used by pose process, but we still deliver it, for log purpose mainly.
        self._send_message(InferenceCommandMessageKind.ProcessLiveWhenReady)

        logger.success("passed %s frames per camera frame_count=%s ; "
                       "tot_skipped_frames=%s cams_frame_idx=%s cams_sent_frame_count=%s",
                       frame_idx, self._intersession_block.frame_count,
                       tot_skipped_frames, cams_frame_idx, cams_sent_frame_count)

    def _put_intersession_frame(self, capture, cam_index: int, frame_idx: int) -> bool:
        ret, frame = capture.read()
        if not ret:
            logger.debug(f"end of video at index {cam_index}")
            return False
        timeout = time.time() + 15   # to be decided if keep or not
        if len(numpy.shape(frame)) >= 3:
            frame = frame[:, :, 0]
        put = self._offline_queue.put
        while time.time() < timeout:
            if put(frame, cam_index, frame_idx, allow_overflow=False) == BufferResult.Ok:
                return True
            # given the current array-multi-queue has no "event" handling we have to retry, at some later point,
            # a good value would be half the duration of the previous, or a recent, inference batch duration,
            # divided by the nbr of frame(s) it contained/had processed.
            time.sleep(0.01)
        logger.error("cam %s: timeout waiting offline_queue has space", cam_index)
        return False

    def _intersession_process(self):
        try:
            result = intersession_process(self._project)
        except Exception as err:
            logger.exception("Error processing intersession: %s", err)
            processed_ok = False
        else:
            processed_ok = True
            self.detection_result_ready(result)

        self._intersession_detection.configuration.complete(self._intersession_detection.configuration.nonce,
                                                            processed_ok)
        self._intersession_block = None
