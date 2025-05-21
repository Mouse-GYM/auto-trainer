import multiprocessing
import os
import queue
import signal
import time
import typing
from itertools import chain
from pathlib import Path
from typing import Optional, Union, List
from dataclasses import dataclass
from enum import Enum
from multiprocessing import Queue
from threading import Thread

import cv2
import h5py
import numpy
import pandas
from h5py import Dataset

from autotrainer.core import FixedArrayMultiQueue, ObservableObject, ProjectInfo, EventManager, clear_queue, \
    InferenceConfiguration
from autotrainer.core.fixed_array_queue import BufferResult
from autotrainer.core.logging import get_verbose_logger
from autotrainer.behavior import SegmentationConfiguration, DetectionConfiguration, intersession_inference, \
    intersession_process, BehaviorEventKind, InferenceProtocol
from autotrainer.core.multiproc import get_mp_ctx
from autotrainer.inference import PoseProcess, InferenceCommandMessageKind, InferenceStatusMessageKind, PoseAlgorithm, \
    DlcPoseModel, MemoryPoseModel, InferenceMode
from tools.acquisition.model.project_dependent_protocol import ProjectDependentProtol

logger = get_verbose_logger(__name__)


def _close_fhs(cams_frame_idx_fhs):
    for idx, fh in enumerate(cams_frame_idx_fhs or []):
        if fh is not None:
            logger.debug("closing %s", fh.name)
            fh.flush()
            fh.close()
            cams_frame_idx_fhs[idx] = None


def _close_h5(fhs: List[h5py.File]):
    for idx, fh in enumerate(fhs or []):
        logger.info("exiting %s", fh.name)
        # fh.flush()
        fh.__exit__(None, None, None)
        fh.close()
        fhs[idx] = None


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

    def __post_init__(self):
        self.pose_data = numpy.empty((0, self.parts_count * 3), dtype=numpy.float32)
        self.pose_data_list = []


@dataclass
class IntersessionDetection:
    configuration: DetectionConfiguration


def check_frame_count(file_path: Path) -> Optional[cv2.VideoCapture]:
    capture = cv2.VideoCapture(file_path.as_posix())
    count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
    if count < 1:
        capture.release()
        return None
    logger.verbose("Opened %s: tot_frames=%s size=%s", file_path, count, file_path.stat().st_size)
    return capture


class InferenceModel(ObservableObject, InferenceProtocol, ProjectDependentProtol):
    def __init__(self, pose_algorithm: PoseAlgorithm):
        super().__init__(event_names=(
            'pose_response_ready',
            'detection_result_ready',
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
        self._send_message(InferenceCommandMessageKind.ProcessOffline)
        time.sleep(0.05)
        self._offline_thread = Thread(target=self._feed_intersession_analysis)
        self._offline_thread.start()

    def perform_detection(self, configuration: DetectionConfiguration):
        logger.info("performing detection analysis")
        self._check_previous_offline_thread()
        self._intersession_detection = IntersessionDetection(configuration)
        self._offline_thread = Thread(target=self._intersession_process)
        self._offline_thread.start()

    # unused
    def perform_live(self):
        pass

    def start(self, network_queue: FixedArrayMultiQueue) -> bool:
        # if self._msg_thread is None:
        #     self._msg_thread = Thread(target=self._monitor_msg_queue)
        #     self._msg_thread.start()

        if self._data_thread is None:
            self._data_thread = Thread(target=self._monitor_data_queue)
            self._data_thread.start()

        if network_queue is None:
            logger.warning("pellet not started because there is no pellet image queue")
            self._set_status(InferenceStatus.stopped)
            return False

        self._frame_height, self._frame_width = network_queue.shape
        self._frames_per_camera = network_queue.frames_per_camera

        self._offline_queue = FixedArrayMultiQueue(
            network_queue.depth,
            network_queue.camera_count,
            network_queue.frames_per_camera,
            network_queue.shape,
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
        if self._process is not None:
            self._set_status(InferenceStatus.stopping)
            self._send_message(InferenceCommandMessageKind.Terminate)

            logger.debug(f"<pellet> waiting for process termination")

            t_timeout_sigint = time.time() + 10
            t_timeout_sigterm = time.time() + 20
            while True:
                t = time.time()
                if t > t_timeout_sigterm:
                    logger.warning("sending SIGTERM to %s", self._process)
                    self._process.terminate()
                    break
                if t > t_timeout_sigint:
                    t_timeout_sigint += 4
                    logger.warning("sending SIGINT to %s", self._process)
                    os.kill(self._process.pid, signal.SIGINT)
                if not self._process.is_alive():
                    break
                time.sleep(0.1)
            self._process.join()
            logger.debug(f"<pellet> process terminated")
            self._process = None

            self._set_status(InferenceStatus.stopped)

            clear_queue(self._data_queue)
            clear_queue(self._msg_queue)
            clear_queue(self._cmd_queue)

    def terminate(self):
        self.stop()
        self._is_running = False

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
                msg, context = self._msg_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            logger.debug("Processing msg %s ...", msg)
            try:
                if msg == InferenceStatusMessageKind.Initialized:
                    self._set_status(InferenceStatus.waiting)
                    self._algorithm.initialize(context)
                    self._send_message(InferenceCommandMessageKind.Start)
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
        # pose_fhs: Optional[List[h5py.File]] = None
        cams_read_h5_dss: List[h5py.Dataset] = []
        cams_read_h5_idx: List[int] = []
        recording_in_progress = False
        prev_mode = None
        prev_session = None
        tot_written_to_live = None
        t_log_counters = time.time()
        tot_skipped = cnt_data_received = 0

        while self._is_running:

            # t_now = time.time()
            # if t_now > t_log_counters:
            #     t_log_counters = t_now + 5
            #     logger.info("data=%s", cnt_data_received)
            #     cnt_data_received = 0

            try:
                msg, context = self._msg_queue.get_nowait()
            except queue.Empty:
                pass
            else:
                logger.debug("Processing msg %s ...", msg)
                try:
                    if msg == InferenceStatusMessageKind.Initialized:
                        self._set_status(InferenceStatus.waiting)
                        self._algorithm.initialize(context)
                        self._send_message(InferenceCommandMessageKind.Start)
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

            try:
                (pose_data, mode, frames_indices) = self._data_queue.get_nowait()   # (timeout=0.1)
            except queue.Empty:
                time.sleep(0.005)
                continue

            cnt_data_received += 1

            prj = self.project
            ib: Optional[IntersessionBlock] = self._intersession_block
            try:
                if prev_mode != mode:
                    logger.verbose("Detected inference mode change -> %s frames=%s", mode, frames_indices)
                if recording_in_progress:
                    if (
                        mode == InferenceMode.Offline
                        # or self._status != InferenceStatus.live  # not sure needed
                        or pose_data is None
                        # or frames_indices is None
                        # or any(fr_i < 0 for frs in frames_indices for fr_i in frs)
                    ):
                        logger.verbose("Detected stop of recording in progress ; status=%s mode=%s frames indices: %s tot_written=%s",
                                       self._status, mode, frames_indices, tot_written_to_live)
                        recording_in_progress = False
                        _close_fhs(cams_frame_idx_fhs)
                        # _close_h5(pose_fhs)
                        cams_frame_idx_fhs = None
                else:
                    if (pose_data is not None
                        # and self._status == InferenceStatus.live
                        and mode == InferenceMode.Live
                        and frames_indices is not None
                        and all(fr_i >= 0 for frs in frames_indices for fr_i in frs)
                        and prj.session.value != prev_session  # REQUIRED
                    ):
                        tot_written_to_live = 0
                        prev_session = prj.session.value
                        logger.verbose("Detected new record in progress ; status=%s mode=%s frames indices: %s",
                                       self._status, mode, frames_indices)
                        recording_in_progress = True
                        pose_data: List[numpy.ndarray]
                        cams_frame_idx_fhs = []
                        recording_in_progress = True
                        # pose_fhs = []
                        pose_paths = []
                        for cam in cams:
                            _, _, p_indices = prj.get_video_path(cam, allow_overwrite=True)
                            pose_path = Path(prj.get_intersession_pose_path(cam, allow_overwrite=True, suffix="_live"))
                            cams_frame_idx_fhs.append(Path(p_indices).open("a"))
                            pose_paths.append(pose_path)

                if mode == InferenceMode.Live:
                    if cams_frame_idx_fhs is not None and frames_indices is not None:
                        tot_written_to_live += 1
                        for fh, cam_fr_indices in zip(cams_frame_idx_fhs, frames_indices):
                            if fh is not None:
                                fh.write("\n".join(chain(map(str, cam_fr_indices), [""])))
                                fh.flush()
                        columns = pandas.MultiIndex.from_product([self._algorithm.part_names, axis_labels],
                                                                 names=["bodyparts", "coords"])
                        for cdx, (cam_fr_indices, cam_pose_path) in enumerate(zip(frames_indices, pose_paths)):
                            # reminder: pose_data has 1 frame cam1, 1 frame cam2, 1 frame cam1, etc..
                            cur = pose_data[cdx::n_cams]
                            cur = numpy.vstack([f.flatten() for f in cur])
                            indices = range(cur.shape[0])
                            df_xyp = pandas.DataFrame(cur, columns=columns, index=indices)
                            df_xyp["frame_idx"] = cam_fr_indices  # also store the frame idx with the results
                            df_xyp.to_hdf(cam_pose_path,
                                          "df_with_missing",
                                          format="table",
                                          mode="a",
                                          append=True,  # required as well for really concat
                            )
                    # Normalize locations.  Not all consumers will be scaling the location by the original frame size.
                    for frame in pose_data:
                        frame[:, 0] /= self._frame_width
                        frame[:, 1] /= self._frame_height
                    response = self._algorithm.process(pose_data)
                    self.pose_response_ready(response)
                else:
                    assert mode == InferenceMode.Offline
                    if prev_mode == InferenceMode.Live:
                        cams_read_h5_dss = [
                            h5py.File(cam_pose_path)["df_with_missing"]["table"]
                            for cam_pose_path in pose_paths
                        ]
                        cams_read_h5_idx = [0] * n_cams
                        tot_skipped = 0

                    if pose_data is None:
                        # end of intersession replay
                        if ib is not None:
                            for cdx, pdl, cur_h5_idx, cur_h5_dss in zip(
                                    range_cams, ib.pose_data_list, cams_read_h5_idx, cams_read_h5_dss
                            ):
                                while True:
                                    skipped = 0
                                    if cur_h5_idx < len(cur_h5_dss) - 1:
                                        pdl.append(cur_h5_dss[cur_h5_idx][1])
                                        cur_h5_idx += 1
                                        skipped += 1
                                    if skipped == 0:
                                        break
                                logger.debug("cam-%s: read %s final entries from h5 live file",
                                             cdx, skipped)
                            try:
                                m = min(map(len, ib.pose_data_list))
                                logger.notice("assembled %s pose responses,"
                                              " now calling intersession_inference()", m)
                                ib.pose_data = numpy.vstack(
                                    list(chain(
                                        [ib.pose_data],  # supposed the empty init array
                                        (
                                            ib.pose_data_list[cdx][ix].flatten()
                                            for ix in range(m)
                                            for cdx in range_cams
                                        )
                                    ))
                                )
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
                    elif ib is not None:
                        # we can now append the received/processed frame data:
                        skipped = 0
                        for cdx, pdl, cur_h5_dss in zip(range_cams, ib.pose_data_list, cams_read_h5_dss):
                            cur_h5_ix = cams_read_h5_idx[cdx]
                            for fx, frame in enumerate(pose_data[cdx::len(cams)]):
                                frame_idx = frames_indices[cdx][fx]
                                # append any of the live processed frame data that are before current received/processed frames:
                                while cur_h5_ix < len(cur_h5_dss) - 1 and cur_h5_dss[cur_h5_ix][2] < frame_idx:
                                    pdl.append(cur_h5_dss[cur_h5_ix][1])
                                    cur_h5_ix += 1
                                    skipped += 1
                                cams_read_h5_idx[cdx] = cur_h5_ix
                                ib.pose_data_list[cdx].append(frame)

                        tot_skipped += skipped
                        t_now = time.time()
                        if tot_skipped > 0 and t_now > t_log_counters:
                            t_log_counters = t_now + 1
                            logger.debug("read %s entries from h5 live file", tot_skipped)
                            tot_skipped = 0


            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as err:
                logger.exception("_monitor_data_queue: loop error processing mode=%s %s: %s",
                                 mode, type(pose_data), err)
            prev_mode = mode
        # end while is_running.

    def _feed_intersession_analysis(self):
        try:
            self.__feed_intersession_analysis()
        except Exception as err:
            logger.exception("_feed_intersession_analysis: error: %s", err)
            EventManager.default().post_event_content(BehaviorEventKind.intersessionSegmentationError, context=str(err))
            self._send_message(InferenceCommandMessageKind.ProcessLiveWhenReady)
            self._intersession_block.configuration.complete(self._intersession_block.configuration.nonce, False)
            self._intersession_block = None

    def __feed_intersession_analysis(self):
        cams = (self._project.camera_1, self._project.camera_2)
        n_cams = len(cams)
        cams_paths = [
            tuple(map(Path, self._project.get_video_path(name=cam, allow_overwrite=True)))
            for cam in cams
        ]
        tot_skipped_frames = 0
        empty_frame = numpy.zeros((self._frame_height, self._frame_width), dtype=numpy.uint8)
        # NB: we are not waiting for the capture threads to close their writing side to the video file(s)
        # so this small sleep, for them to get more chance to do it:
        time.sleep(0.5)
        # This is to not get "moov-atom-not-found" in stderr output from opencv library.
        timeout = time.time() + self._intersession_wait_time
        captures_d = {}
        while len(captures_d) < n_cams:
            for cdx, cam in enumerate(cams):
                if cdx not in captures_d:
                    capture = check_frame_count(cams_paths[cdx][0])
                    if capture is not None:
                        captures_d[cdx] = capture
            if time.time() > timeout:
                EventManager.default().post_event_content(BehaviorEventKind.intersessionSegmentationInputError)
                raise RuntimeError("timeout waiting for intersession video files")

        captures: List[cv2.VideoCapture] = [captures_d[cdx] for cdx in range(len(cams))]
        cams_processed_fhs = [
            (None if not p.exists() or p.stat().st_size == 0 else p.open())
            for _, _, p in cams_paths
        ]

        frame_idx = 0
        cams_sent_frame_count = [0] * n_cams
        cams_frame_idx = [0] * n_cams
        cams_already_processed_idx = [
            -1 if fh is None else int(fh.readline().strip())
            for fh in cams_processed_fhs
        ]
        logger.debug("first cams_already_processed_idx=%s", cams_already_processed_idx)
        all_read = [False] * n_cams
        while True:
            # skip frames already processed during live:
            for cdx, fh in enumerate(cams_processed_fhs):
                if fh is not None:
                    skipped = 0
                    while cams_frame_idx[cdx] == cams_already_processed_idx[cdx]:
                        skipped += 1
                        tot_skipped_frames += 1
                        ret, _ = captures[cdx].read()
                        if not ret:
                            all_read[cdx] = True
                            break
                        cams_frame_idx[cdx] += 1
                        val = fh.readline().strip()
                        if val == "":
                            fh.close()
                            cams_processed_fhs[cdx] = None
                            break
                        else:
                            cams_already_processed_idx[cdx] = int(val)
                    if skipped > 0:
                        logger.spam("cam-%s: skipped=%s", cdx, skipped)

            # cams can be "desynchronized" when being recorded to disk...
            for cdx, (cap, fr_idx) in enumerate(zip(captures, cams_frame_idx)):
                if not all_read[cdx]:
                    if not self._put_intersession_frame(cap, cdx, fr_idx):
                        all_read[cdx] = True
                    cams_sent_frame_count[cdx] += 1
                cams_frame_idx[cdx] += 1
            frame_idx += 1

            if any(all_read):
                # stop on first cam record entirely read/consumed.
                break
        # end while True

        # fill current batch of each cam:
        for cdx, cnt in enumerate(cams_sent_frame_count):
            r = self._frames_per_camera - cnt % self._frames_per_camera
            if r != self._frames_per_camera:
                logger.debug("cam-%s: padding %s empty frames to cam", cdx, r)
                for _ in range(r):
                    while self._offline_queue.put(empty_frame, cdx, -1, allow_overflow=False) != BufferResult.Ok:
                        time.sleep(0.001)

        logger.notice("passed %s frames per camera ; tot_skipped_frames=%s ; per cam last frame idx: %s ; cams frame sent count: %s",
                    frame_idx, tot_skipped_frames, cams_frame_idx, cams_sent_frame_count)
        self._intersession_block.frame_count = frame_idx
        self._send_message(InferenceCommandMessageKind.ProcessLiveWhenReady)

    def _put_intersession_frame(self, capture, cam_index: int, frame_idx: int) -> bool:
        ret, frame = capture.read()
        if not ret:
            logger.debug(f"end of video at index {cam_index}")
            return False
        timeout = time.time() + 600   # to be decided if keep or not
        if len(numpy.shape(frame)) >= 3:
            frame = frame[:, :, 0]
        put = self._offline_queue.put
        while time.time() < timeout:
            res = put(frame, cam_index, frame_idx, allow_overflow=False)
            if res == BufferResult.Ok:
                return True
            time.sleep(0.001)
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
