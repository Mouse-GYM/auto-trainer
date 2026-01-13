
import logging.config
import multiprocessing
import os
import queue
import statistics
import signal
import threading
import time
from enum import Enum
from itertools import chain
from multiprocessing import synchronize
from pathlib import Path
from typing import Optional, Dict, List, TextIO

import h5py
import numpy
import pandas

from autotrainer.core import ProjectInfo
from autotrainer.core.frame_index import FrameIndexCategory
from autotrainer.core.multiproc import get_mp_ctx
from autotrainer.core.logging import get_verbose_logger, make_log_dict_config, setup_logging, install_log_exception_hook

from autotrainer.inference import InferenceMode, PoseAlgorithm
from .analysis.intersession_inference import intersession_inference

logger = get_verbose_logger(__name__)


# even better is to use __debug__ and use "python -O ..."
# see https://docs.python.org/3/using/cmdline.html#cmdoption-O
_local_do_debug = False


def _shorten_text_file(lines: List[str], path: Path, limit: int):
    with path.open("w") as fh:
        fh.write("\n".join(chain(lines[:limit], [''])))


def _close_fhs(cams_frame_idx_fhs: Optional[List[Optional[TextIO]]]):
    if cams_frame_idx_fhs is None:
        return
    closed = []
    for idx, fh in enumerate(cams_frame_idx_fhs):
        if fh is not None:
            closed.append(fh.name)
            logger.debug("closing %s", fh.name)
            fh.flush()
            fh.close()
            cams_frame_idx_fhs[idx] = None
    if len(closed) > 0:
        logger.verbose("closed fhs: %s", closed)


def _close_h5(fhs: List[Optional[h5py.File]]):
    for idx, fh in enumerate(fhs or []):
        if fh is not None:
            logger.info("closing %s", fh.name)
            # fh.flush()
            fh.__exit__(None, None, None)
            fh.close()
            fhs[idx] = None


def open_h5_file(file_path: Path):
    datasets = h5py.File(file_path)["df_with_missing"]["table"]
    logger.debug("%s: %s entries", file_path, len(datasets))
    return datasets

#

def _send_command(func):
    def wrapped(self, *args, **kwargs):
        self._send_msg(func.__name__, args, kwargs)
    return wrapped


class InferenceMonitorDataMsg(str, Enum):

    SET_PROJECT_INFO = "set_project_info"
    SET_POSE_ALGO = "set_pose_algo"
    POSE_RESULT_READY = "pose_result_ready"
    INTERSESSION_RESULT_READY = "intersession_result_ready"
    START_NEW_INTERSESSION_BATCH_ITEM = "start_new_intersesson_batch_item"


class InferenceMonitorDataProc(multiprocessing.Process):

    Msg = InferenceMonitorDataMsg

    def __init__(
        self,
        *,
        project: ProjectInfo,
        pose_data_queue: multiprocessing.Queue,
        cmd_queue: multiprocessing.Queue,
        cmd_ack_event: synchronize.Event,
        msg_queue: multiprocessing.Queue,
        frames_per_cam: int,
        monitored_parts_offsets,
    ):
        mp_ctx = get_mp_ctx()
        log_dict_config = make_log_dict_config()
        super().__init__(
            name=self.__class__.__name__,
            target=self._do_run,
            kwargs=dict(
                project=project,
                log_dict_config=log_dict_config,
            ),
            daemon=True,
        )
        self._project = project
        self._data_queue = pose_data_queue
        self._cmd_queue = cmd_queue
        self._cmd_ack_event = cmd_ack_event
        self._msg_queue = msg_queue
        self._cams = (project.camera_1, project.camera_2)
        self._frames_per_camera = frames_per_cam
        self._recording_live_batch = int(os.getenv("INFERENCE_LIVE_BATCH", 150 * 5))  # 5s at 150 FPS
        self._monitored_parts_offsets = monitored_parts_offsets
        self._parts_offsets = 0
        self._stop_recorded = mp_ctx.Event()
        self._pose_algo: Optional[PoseAlgorithm] = None
        self._is_running = True

    @property
    def stop_recorded(self) -> multiprocessing.Event:  # noqa
        return self._stop_recorded

    def _do_run(self, *, project, log_dict_config: Optional[Dict]):
        signal.signal(signal.SIGINT, signal.SIG_IGN)

        if log_dict_config is None:
            setup_logging()
        else:
            logging.config.dictConfig(log_dict_config)
            install_log_exception_hook()
        #
        cmd_thread = threading.Thread(target=self._monitor_cmd_queue, daemon=True)
        cmd_thread.start()
        logger.info("Running monitor_data_queue")
        try:
            self._monitor_data_queue(project)
        except BaseException as err:
            logger.exception("Fatal error: %s", err)
        self._is_running = False  # before below put
        self._cmd_queue.put(None)  # ensure monitor cmd thread will exit too
        cmd_thread.join(3)
        flushed = 0
        while True:
            try:
                self._cmd_queue.get_nowait()
            except queue.Empty:
                break
            flushed += 1
        logger.debug("Exiting ; cmd_thread alive: %s ; cmd_queue_flushed=%s", cmd_thread.is_alive(), flushed)

    def _monitor_cmd_queue(self):
        while self._is_running:
            raw = self._cmd_queue.get()
            if raw is None:
                self._is_running = False
                break
            cmd, args, kwargs = raw
            logger.debug("Processing cmd %s with %s // %s", cmd, args, kwargs)
            if cmd is self.Msg.SET_POSE_ALGO:
                self._pose_algo =  args[0]
            elif cmd is self.Msg.SET_PROJECT_INFO:
                self._project = args[0]
            elif cmd is self.Msg.START_NEW_INTERSESSION_BATCH_ITEM:
                # Without session batching the stop-recorded event is normally set via the data handler thread,
                # when it receive the EOF_RECORDING which is initially sent by the camera capture processes to the
                # main pose/inference thread-process itself.
                # While with session batching we have to set it "explicitly", after enter intersession.
                self._stop_recorded.set()  # so here it is.
            self._cmd_ack_event.set()

    def _send_msg(self, msg, *args, **kwargs):
        self._msg_queue.put((msg, (args, kwargs)))

    def _intersession_post_process(
        self,
        project_info: ProjectInfo,
        perf_c_start_offline,
        pose_algo,
        range_cams, ib_pose_data_list, ib_pose_data_dict, cams_read_h5_idx, cams_read_h5_dss,
    ):
        logger.notice("Processing intersession offline post-process ..")
        fill_live_end = True
        for cdx, pdl, cur_h5_idx, cur_h5_dss in zip(
            range_cams, ib_pose_data_list, cams_read_h5_idx, cams_read_h5_dss
        ):
            skipped = 0
            while fill_live_end and cur_h5_idx < len(cur_h5_dss):
                ds_row = cur_h5_dss[cur_h5_idx]
                pdl.append(ds_row[1])
                if __debug__ and _local_do_debug:
                    pdd = ib_pose_data_dict[cdx]
                    pdd[ds_row[2][0]] = ds_row[1]
                cur_h5_idx += 1
                skipped += 1
            logger.debug("cam-%s: read %s final entries from h5 live file",
                         cdx, skipped)
        try:
            # if _local_do_debug:
            #     diffs = [
            #         set(range(len(ib_pose_data_dict[cdx]))) - set(ib_pose_data_dict[cdx])
            #         for cdx in range(self._camera_count)
            #     ]
            #     if any(diffs):
            #         logger.warning("seen missing frame indices: %s", diffs)
            #     for cdx, p in enumerate(pose_paths):
            #         with open(str(p) + ".idx_monitor_data_q.txt", "w") as fh:
            #             fh.write("\n".join(chain(map(str, sorted(ib_pose_data_dict[cdx])), [''])))

            min_nbr_pd = min(map(len, ib_pose_data_list))

            # current analyse code also require exact same frame number in all cameras,
            # let's trim what's necessary:
            for cam in self._cams:
                paths = list(map(Path, project_info.get_video_path(cam, allow_overwrite=True)))
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

            ib_pose_data = numpy.empty((0, pose_algo.part_count * 3), dtype=numpy.float32)
            final_pose_data = numpy.vstack(
                list(chain(
                    [ib_pose_data],  # supposed the empty init array
                    (
                        pdl[ix]
                        for ix in range(min_nbr_pd)
                        for pdl in ib_pose_data_list
                    )
                ))
            )
            logger.notice("assembled %s pose responses, speed=%.3f/s (vstack=%s)"
                          " now calling intersession_inference()",
                          min_nbr_pd, 2 * min_nbr_pd / (time.perf_counter() - perf_c_start_offline), final_pose_data.shape[0])

            intersession_inference(final_pose_data, self._pose_algo.part_names,
                                   project_info)
            success = True
            logger.success("fully processed session-%s inference with %s total pose responses",
                           project_info.session, final_pose_data.shape[0])
        except Exception as err:
            logger.exception("Error during intersession_inference: %s", err)
            success = False

        self._send_msg(self.Msg.INTERSESSION_RESULT_READY, project_info.session, success)

    def _monitor_data_queue(self, project: ProjectInfo):
        pose_data: Optional[List[numpy.ndarray]]
        frames_indices: Optional[numpy.ndarray]

        frames_per_batch = 3
        cams = [project.camera_1, project.camera_2]
        n_cams = len(cams)
        range_cams = list(range(n_cams))
        cams_frame_idx_fhs = None
        pose_paths: List[Path] = []
        cams_read_h5_dss: List[h5py.Dataset] = []
        cams_read_h5_idx: List[int] = []
        recording_in_progress = False
        next_prev_mode = None
        cur_local_prj = None
        tot_written_to_live = None
        cnt_data_received = 0
        skip_update = False
        pose_data = []

        thread_post_process: Optional[threading.Thread] = None
        ib_pose_data_list = []
        ib_pose_data_dict = []

        writes_h5_live_durations = []
        cur_h5_live_batch = [[] for _ in range_cams]
        cur_cams_indices = [[] for _ in range_cams]
        tot_skipped = 0
        perf_c_start_offline = 0
        skip_next_pose_data = 0

        perf_c_log_counters = time.perf_counter()
        t_perf_live_check_data_queue_size = time.perf_counter() + 5

        def get_next_pose_data(timeout: Optional[float] = 0.05):
            nonlocal pose_data
            prev_pose_data = pose_data
            tot_flushed = 0
            if prev_pose_data is None:
                cur_qsize = self._data_queue.qsize()
                assert prev_mode == InferenceMode.Offline
                assert recording_in_progress is False
                # ensure we won't try flush again if the queue is actually empty on first try:
                pose_data = []
            else:
                cur_qsize = 0

            next_pose_data = next_mode = next_frames_indices = None

            while self._is_running:
                if prev_pose_data is None:
                    try:
                        next_pose_data, next_mode, next_frames_indices = self._data_queue.get_nowait()
                    except queue.Empty:
                        if tot_flushed > 0:
                            # defensive:
                            # will so return the previous next_pose_data, next_mode, next_frames_indices
                            break
                        raise  # nothing we can do, so re-raise to caller
                else:
                    next_pose_data, next_mode, next_frames_indices = self._data_queue.get(timeout=timeout)
                    break
                if (
                    next_mode != InferenceMode.Live
                    or next_frames_indices is None
                    or not (next_frames_indices == FrameIndexCategory.ONLINE_NO_RECORDING).all()
                    or tot_flushed >= cur_qsize # - 1  # so return the last one
                    # removed -1 :
                    # all the previous data in the queue might be, or is, from BEFORE the start of the intersession,
                    # otherwise we would be possibly executing some state events using too old data.
                ):
                    break
                tot_flushed += 1
            # end while True
            if prev_pose_data is None:
                logger.verbose("flushed queue after end of offline processing ; size=%s flushed=%s",
                               cur_qsize, tot_flushed)
                nonlocal skip_next_pose_data
                skip_next_pose_data = 0
            return next_pose_data, next_mode, next_frames_indices

        def write_h5_batch(dst_path, data_list, indices_list):
            t0 = time.perf_counter()
            arr = numpy.vstack(data_list)
            index = list(range(arr.shape[0]))
            df_xyp = pandas.DataFrame(arr,
                                      columns=pose_algo.pose_result_columns, index=index)
            df_xyp["frame_idx"] = list(indices_list)  # also store the frame idx with the results
            logger.spam("Writing batch to %s", dst_path)
            # logger.verbose("writing h5 batch (%s/%s entries): indices=%s to %s (prev-exists: %s)",
            #                len(df_xyp), len(arr), indices_list, dst_path, os.path.exists(dst_path))
            df_xyp.to_hdf(dst_path,
                          "df_with_missing",
                          format="table",
                          mode="a",
                          append=True,  # required as well for really concat
                          )
            data_list.clear()
            indices_list.clear()
            # logger.debug("cleared lists %s and %s",
            #              object.__repr__(data_list), object.__repr__(indices_list))
            t1 = time.perf_counter()
            d = t1 - t0
            logger.debug("wrote h5 batch (%s) in %sms to %s",
                           len(df_xyp), int(d * 1000), dst_path)
            writes_h5_live_durations.append(d)

        # main loop
        while self._is_running:

            perf_now = time.perf_counter()
            if perf_now > perf_c_log_counters:
                perf_c_log_counters = perf_now + 15
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("qlen=%s data=%s avg_writes_h5_live=%.6f skipped_h5_live=%s",
                                self._data_queue.qsize(), cnt_data_received,
                                0 if len(writes_h5_live_durations) == 0 else statistics.mean(writes_h5_live_durations),
                                 tot_skipped)
                cnt_data_received = 0
                tot_skipped = 0
                writes_h5_live_durations.clear()

            prev_mode = next_prev_mode  # don't forget

            try:
                (pose_data, mode, frames_indices) = get_next_pose_data()
            except queue.Empty:
                continue

            if prev_mode != mode:
                logger.verbose("Detected inference mode change -> %s frames=%s",
                               mode, frames_indices.tolist())
                if mode == InferenceMode.Live:
                    skip_next_pose_data = 3
                    # skip next 3 pose data to flush anything remaining
                    # NB: this looks necessary/required to ensure the inference gives back "reliable" result,
                    # with skip=2, for instance, we ~always get a first result without all visible elements detected.

            if mode == InferenceMode.Live:
                perf_now = time.perf_counter()
                if perf_now >= t_perf_live_check_data_queue_size:
                    data_queue_size = self._data_queue.qsize()
                    skip_update = data_queue_size > 7
                    if skip_update:
                        logger.warning("data queue size=%s ; skip_update", data_queue_size)
                    t_perf_live_check_data_queue_size = perf_now + (0.5 if skip_update else 2.5)
            else:
                skip_update = False

            next_prev_mode = mode

            if __debug__ and frames_indices is not None:
                if (not (frames_indices >= 0).all()
                    and not (frames_indices == FrameIndexCategory.ONLINE_NO_RECORDING).all()
                ):
                    logger.debug("mode=%s frames_indices=%s", mode, frames_indices.tolist())

            pose_algo = self._pose_algo
            if pose_algo is None:
                continue

            if recording_in_progress and frames_indices is not None:
                # thx to camera capture which send a full EOF_RECORDING batch frames indices,
                # this condition allows to know when to close/stopping writing to live files,
                # and reopen for offline mode
                if (frames_indices[:, 0] == FrameIndexCategory.EOF_RECORDING).any():
                    recording_in_progress = False
                    logger.notice("Detected stop of recording in progress ; mode=%s prev=%s frames_indices=%s",
                                  mode, prev_mode, frames_indices.tolist())
                    _close_fhs(cams_frame_idx_fhs)
                    cams_frame_idx_fhs = None
                    for cam_pose_path, cam_indices, cam_h5_live in zip(pose_paths, cur_cams_indices, cur_h5_live_batch):
                        if len(cam_h5_live) == 0:
                            continue
                        write_h5_batch(cam_pose_path, cam_h5_live, cam_indices)
                    #
                    logger.debug("setting stop recorded on %s", self._stop_recorded)
                    self._stop_recorded.set()  # this is for the feeder thread to know when it can open the data files

            cnt_data_received += 1

            try:
                if (
                    not recording_in_progress
                    and pose_data is not None
                    and mode == InferenceMode.Live
                    and frames_indices is not None
                    and (frames_indices[:, 0] >= 0).any()
                ):
                    tot_written_to_live = 0
                    recording_in_progress = True
                    cur_local_prj = self._project.to_local_value()
                    logger.notice("Detected new record in progress ; session=%s ; mode=%s frames indices: %s",
                                   cur_local_prj.session, mode, frames_indices.tolist())
                    self._stop_recorded.clear()
                    cams_frame_idx_fhs = []
                    pose_paths = []
                    cur_h5_live_batch = [[] for _ in range_cams]  # safer
                    cur_cams_indices = [[] for _ in range_cams]  # safer
                    ib_pose_data_list = [[] for _ in range_cams]
                    ib_pose_data_dict = []
                    if __debug__:
                        ib_pose_data_dict = [{} for _ in range_cams]
                    for cam in cams:
                        _, _, p_indices = cur_local_prj.get_video_path(cam, allow_overwrite=True)
                        cams_frame_idx_fhs.append(Path(p_indices).open("w"))
                        pose_path = Path(cur_local_prj.get_intersession_pose_path(cam, allow_overwrite=True, suffix="_live"))
                        pose_paths.append(pose_path)

                if mode == InferenceMode.Live:

                    if recording_in_progress:
                        tot_written_to_live += 1
                        for fh, cam_fr_indices in zip(cams_frame_idx_fhs, frames_indices):
                            cam_fr_indices = list(filter(lambda i: i >= 0, cam_fr_indices))
                            if fh is not None and len(cam_fr_indices) > 0:
                                fh.write("\n".join(map(str, chain(cam_fr_indices, [""]))))
                                fh.flush()

                        for cdx, cam_fr_indices, cam_pose_path, cam_h5_live, cam_indices in zip(
                            range_cams, frames_indices, pose_paths, cur_h5_live_batch, cur_cams_indices
                        ):
                            # reminder: pose_data has 1 frame cam1, 1 frame cam2, 1 frame cam1, etc..
                            cur = pose_data[cdx::n_cams]
                            cur = {
                                fx: f.flatten()
                                for fx, f in zip(cam_fr_indices, cur)
                                if fx >= 0
                            }
                            cur = [cur[ix] for ix in sorted(cur)]  # should not be needed
                            if len(cur) == 0:
                                continue
                            cam_h5_live.append(cur)
                            cam_indices.extend(filter(lambda ix: ix >= 0, cam_fr_indices))
                            if len(cam_h5_live) * frames_per_batch >= self._recording_live_batch:
                                write_h5_batch(cam_pose_path, cam_h5_live, cam_indices)

                    if skip_next_pose_data > 0:
                        skip_next_pose_data -= 1
                        continue

                    if skip_update:
                        continue

                    if (frames_indices < FrameIndexCategory.ONLINE_NO_RECORDING).any():
                        # this is normal for stop recording
                        if not (frames_indices < FrameIndexCategory.ONLINE_NO_RECORDING).all():
                            logger.verbose("Skipping incomplete frame index pose_data: %s",frames_indices.tolist())
                        continue

                    response = pose_algo.process(pose_data, pairs_3d_offsets=self._monitored_parts_offsets)
                    self._send_msg(self.Msg.POSE_RESULT_READY, response)

                elif mode == InferenceMode.Offline:

                    if (
                        pose_data is not None
                        and len(cams_read_h5_dss) == 0
                        and frames_indices is not None and (frames_indices >= 0).any()
                        # with random cam there might be no frame to replay, so we get immediately all < 0
                    ):
                        _close_fhs(cams_frame_idx_fhs)  # just to be sure
                        cams_frame_idx_fhs = None
                        perf_c_start_offline = time.perf_counter()
                        logger.notice("Opening live files for offline processing ; prev_mode=%s frames=%s",
                                      prev_mode, frames_indices.tolist())
                        cur_local_prj = self._project.to_local_value()
                        # re-obtain the paths, projectinfo might be from a batch session
                        pose_paths = [
                            Path(cur_local_prj.get_intersession_pose_path(cam, allow_overwrite=True, suffix="_live"))
                            for cam in cams
                        ]
                        cams_read_h5_dss = [
                            open_h5_file(cam_pose_path)
                            for cam_pose_path in pose_paths
                        ]
                        cams_read_h5_idx = [0] * n_cams
                        ib_pose_data_list = [[] for _ in range_cams]
                        ib_pose_data_dict = []
                        if __debug__:
                            ib_pose_data_dict = [{} for _ in range_cams]
                        tot_skipped = 0
                        logger.debug("setting stop recorded on %s", self._stop_recorded)
                        self._stop_recorded.set()  # this is for the feeder thread to know when it can open the data files

                    # after check for event start/restart of offline processing:

                    if pose_data is None:
                        # end of intersession replay
                        logger.verbose("detected end of inference offline processing ; project=%s",
                                       cur_local_prj)
                        # we can reset the offline queue here, it's safe :
                        # the pose process has switched to its online queue at this point
                        self._stop_recorded.clear()
                        _close_fhs(cams_frame_idx_fhs)  # defensive as supposed to be close already
                        cams_frame_idx_fhs = None
                        if thread_post_process is not None:
                            logger.debug("joining previous thread_post_process")
                            thread_post_process.join()
                        thread_post_process = threading.Thread(
                            name="OfflinePostProcess",
                            target=self._intersession_post_process,
                            args=(
                                cur_local_prj,
                                perf_c_start_offline,
                                pose_algo,
                                range_cams,
                                ib_pose_data_list,
                                ib_pose_data_dict,
                                cams_read_h5_idx,
                                cams_read_h5_dss,
                            ),
                            daemon=True,
                        )
                        thread_post_process.start()
                        cams_read_h5_dss = []
                        ib_pose_data_list = []
                        ib_pose_data_dict = []
                    else:
                        assert pose_data is not None
                        if (frames_indices < FrameIndexCategory.ONLINE_NO_RECORDING).all():
                            # happens for EOF_OFFLINE_PROCESSING
                            continue
                        # we can now append the received/processed frame data:
                        skipped = 0
                        # append any of the live processed frame data that are before current
                        # received/processed frames indices:
                        for cdx, pdl, cur_h5_dss, cam_fr_indices in zip(
                            range_cams, ib_pose_data_list, cams_read_h5_dss, frames_indices
                        ):
                            cur_h5_ix = cams_read_h5_idx[cdx]
                            for fx, frame in enumerate(pose_data[cdx::len(cams)]):
                                frame_idx = cam_fr_indices[fx]
                                if frame_idx < 0:  # == FrameIndexCategory.PADDING:
                                    __debug__ and \
                                    logger.spam("cam-%s : fx=%s got negative frame idx: %s",
                                                 cdx, fx, cam_fr_indices)
                                    continue
                                    # break
                                while cur_h5_ix < len(cur_h5_dss) and frame_idx > cur_h5_dss[cur_h5_ix][2]:
                                    ix = cur_h5_dss[cur_h5_ix][2][0]
                                    f = cur_h5_dss[cur_h5_ix][1]
                                    if __debug__ and _local_do_debug:
                                        pdd = ib_pose_data_dict[cdx]
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
                                if __debug__ and _local_do_debug:
                                    pdd = ib_pose_data_dict[cdx]
                                    if (frame_idx != len(pdl) and frame_idx < len(cur_h5_dss)) or frame_idx in pdd:
                                        logger.warning("cam-%s: detected invalid frame idx: %s vs %s - double=%s",
                                                       cdx, frame_idx, len(pdl), frame_idx in pdd)
                                    pdd[frame_idx] = f
                                pdl.append(f)

                        tot_skipped += skipped

            except Exception as err:
                logger.exception("_monitor_data_queue: loop error processing mode=%s %s: %s",
                                 mode, type(pose_data), err)


