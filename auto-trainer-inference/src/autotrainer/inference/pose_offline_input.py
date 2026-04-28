import multiprocessing
import queue
import threading
import time
from itertools import chain
from multiprocessing import synchronize
from pathlib import Path
from typing import Tuple, Optional, Dict, List

import cv2
import h5py
import numpy
import numpy as np

from autotrainer.core import ProjectInfo, FrameIndexCategory, get_perf_now, get_verbose_logger

_local_do_debug = True

logger = get_verbose_logger(__name__)


class InferenceIncorrectStatus(RuntimeError):
    """For when in analysis but inference change status"""


def check_frame_count(file_path: Path):
    capture = cv2.VideoCapture(file_path.as_posix())
    count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if count < 1:
        capture.release()
        return None, None
    logger.verbose("Opened %s: tot_frames=%s size=%s", file_path.name, count, file_path.stat().st_size)
    return capture, count



class OfflineInputProcess:

    def __init__(
        self,
        *,
        stop_recorded: synchronize.Event,
        frame_shape: Tuple[int, ...],
        frames_per_cam: int,
        nr_cams: int,
        msg_queue: multiprocessing.Queue,
    ):
        self._project = None
        self._cur_project_info: Optional[ProjectInfo] = None
        self._live_requested = False
        self._interrupted = False
        self._frame_shape = frame_shape
        self._nr_cams = nr_cams
        self._frames_per_cam = frames_per_cam
        self._frames_per_batch = frames_per_cam * nr_cams
        self._msg_queue = msg_queue
        self._stop_recorded = stop_recorded
        # NB: using 3 entire different frame buffers,
        # to allow the consumer/reader (pose itself) to process 1 such buffer,
        # while this writer has at least 1 other free buffer to write into at will.
        self._buffer1 = numpy.ndarray(
            (self._frames_per_batch,  # nbr cams (2) * frames per cam (3 atm)
             *frame_shape,  # W, H
             3,  # current model takes RGB
             ))
        self._indices1 = numpy.ndarray(
            (nr_cams, frames_per_cam), dtype="int64")
        # same2:
        self._buffer2 = self._buffer1.copy()
        self._indices2 = self._indices1.copy()
        # same3:
        self._buffer3 = self._buffer1.copy()
        self._indices3 = self._indices1.copy()
        self._sema_ready = threading.Semaphore(0)  # 3 buffers
        self._sema_free = threading.Semaphore(0)  # 3 buffers
        self._cur_batch_nr = 0
        self._cur_put_frame_idx = 0  # current frame count in current batch buffer [0, fames_per_cam * nr_cams - 1]
        self._cur_buffer_w = self._buffer1
        self._cur_buffer_r = self._buffer1
        self._cur_cams_buffer_idx = [0] * self._nr_cams
        self._cur_thread: Optional[threading.Thread] = None
        self._empty_frame = numpy.zeros(self._frame_shape, dtype=numpy.uint8)

    def _send_msg(self, kind, data=None):
        self._msg_queue.put((kind, data))

    def set_live(self, live: bool = True):
        self._live_requested = live

    @property
    def live_requested(self) -> bool:
        return self._live_requested

    def has_project_waiting(self):
        cur_th = self._cur_thread
        return cur_th is not None and cur_th.is_alive() and self._project is not None

    def set_project_info(self, project_info: ProjectInfo, *, wait_stop_recorded: bool=True):
        cur_th = self._cur_thread
        prev_prj = self._cur_project_info
        if prev_prj == project_info and cur_th is not None and cur_th.is_alive():
            logger.warning("skipping set_project_info due to already loaded and processing")
            return
        logger.info("Received new project to process: %s", project_info)
        if cur_th is not None:
            if cur_th.is_alive():
                self._interrupted = True
                logger.warning("joining previous offline read thread")
            cur_th.join()
        self._cur_project_info = project_info
        self._live_requested = False
        self._interrupted = False
        self._project = project_info
        for buff, idc in zip((self._buffer1, self._buffer2, self._buffer3),
                             (self._indices1, self._indices2, self._indices3)):
            buff[:] = 0
            idc[:] = FrameIndexCategory.PADDING
        self._cur_buffer_r = self._cur_buffer_w = self._buffer1
        self._cur_cams_buffer_idx = [0] * self._nr_cams
        self._cur_put_frame_idx = 0
        sema_miss = self._sema_ready._value
        logger.debug("acquiring sema_ready %s times", sema_miss)
        for _ in range(sema_miss):
            self._sema_ready.acquire()
        sema_miss = self._sema_free._value
        logger.debug("releasing sema_free %s times", sema_miss)
        for _ in range(3 - sema_miss):  # 3 == current nbr of batch buffers we use (buffer1+2+3)
            self._sema_free.release()
        logger.verbose("sema_ready=%s sema_free=%s", self._sema_ready._value, self._sema_free._value)
        self._cur_batch_nr = 0
        cur_th = self._cur_thread = threading.Thread(
            target=self._feed_intersession_analysis,
            args=(project_info, wait_stop_recorded),
            name="OfflineRead",
            daemon=True,
        )
        cur_th.start()

    def get_output(self, *, timeout: float = 1):
        if self._cur_project_info is None:
            # logger.debug("cur_project_info None")
            # this happens at the end of offline processing, but before detection is finished
            time.sleep(0.01)
            # offline detection takes ~2-3 seconds to process.
            raise queue.Empty
        if self._cur_batch_nr == 0:
            logger.verbose("first get_output")
        if self._live_requested or not self._sema_ready.acquire(timeout=timeout):
            raise queue.Empty
        cur = self._cur_buffer_r
        if cur is self._buffer1:
            idc = self._indices1
            self._cur_buffer_r = self._buffer2
        elif cur is self._buffer2:
            idc = self._indices2
            self._cur_buffer_r = self._buffer3
        else:
            idc = self._indices3
            self._cur_buffer_r = self._buffer1
        self._cur_batch_nr += 1
        if (idc[:, -1] == FrameIndexCategory.EOF_OFFLINE_PROCESSING).all():
            # finally:
            self._cur_project_info = None
            cur_th = self._cur_thread
            if cur_th is not None:  # should be
                logger.verbose("EOF_OFFLINE_PROCESSING ; joining output thread")
                cur_th.join(3)
                if cur_th.is_alive():
                    logger.warning("output thread still alive after join(3), while expected already/fast exited")
                self._cur_thread = None

        return cur, idc

    def release_output(self):
        self._sema_free.release()

    def _put_intersession_frame(self, capture, cam_index: int, frame_idx: int, *, timeout: float = 5) -> bool:
        ret, frame = capture.read()
        if not ret:
            logger.warning("cam-%s: unexpected end of video at index %s", cam_index, frame_idx)
            return False
        if len(numpy.shape(frame)) >= 3:  # unsure we want always this
            frame = frame[:, :, 0]
        return self._put_block(frame, cam_index, frame_idx, timeout=timeout)

    def _put_block(self, frame, cam_index, frame_idx, *, timeout: float=5):
        cur_idx = self._cur_cams_buffer_idx[cam_index]
        if __debug__:
            if self._cur_batch_nr == 0 or frame_idx <= 0:
                logger.debug("cam-%s: frame_idx=%s cur_batch_idx=%s", cam_index, frame_idx, cur_idx)
        cur_buffer = self._cur_buffer_w
        if self._cur_put_frame_idx == 0:
            if not self._sema_free.acquire(timeout=timeout):
                raise RuntimeError(f"cam-{cam_index}: timeout waiting sema_free ; cur_batch={self._cur_batch_nr}")
        if cur_buffer is self._buffer1:
            idc = self._indices1
        elif cur_buffer is self._buffer2:
            idc = self._indices2
        else:
            idc = self._indices3
        off = cam_index + self._nr_cams * cur_idx
        cur_buffer[off, :, :, 0] = frame
        for ch in (1, 2):  # complete RGB:
            cur_buffer[off, :, :, ch] = frame
        idc[cam_index, cur_idx] = frame_idx
        #
        self._cur_cams_buffer_idx[cam_index] = (cur_idx + 1) % self._frames_per_cam
        self._cur_put_frame_idx = (self._cur_put_frame_idx + 1) % self._frames_per_batch
        if self._cur_put_frame_idx == 0:
            self._sema_ready.release()  # signal new batch buffer available for get_output
            if cur_buffer is self._buffer1:
                self._cur_buffer_w = self._buffer2
            elif cur_buffer is self._buffer2:
                self._cur_buffer_w = self._buffer3
            else:
                self._cur_buffer_w = self._buffer1
            if (idc <= 0).any():
                logger.verbose("out indices: %s ; frames==0: %s",
                               idc.tolist(),
                               [(cur_buffer[idx] == 0).all()
                                for idx in range(self._nr_cams * self._frames_per_cam)])
        return True

    def _feed_intersession_analysis(self, project, wait_stop_recorded):
        try:
            self._feed_intersession_analysis_execute(project, wait_stop_recorded)
        except InferenceIncorrectStatus as err:
            got_error = err
        except Exception as err:
            logger.exception("_feed_intersession_analysis: error: %s", err)
            got_error = err
        else:
            got_error = None
        #
        success = got_error is None
        if not success:
            # TODO: how to forward to main process sync ?
            logger.error("feed_intersession_analysis stopped given error=%s prj=%s", got_error, project)
        else:
            logger.info("feed intersession finished. trial_project=%s", project)
        #
        for cdx in range(self._nr_cams):
            missing_for_batch = (
                (self._frames_per_cam - self._cur_cams_buffer_idx[cdx]) % self._frames_per_cam
            )
            logger.verbose("cam-%s: putting %s PADDING on cam ; cams_buff_idx=%s",
                           cdx, missing_for_batch, self._cur_cams_buffer_idx)
            for _ in range(missing_for_batch):
                self._put_block(self._empty_frame, cdx, FrameIndexCategory.PADDING)
        logger.info("sending EOF_OFFLINE_PROCESSING")
        for _ in range(self._frames_per_cam):
            for cdx in range(self._nr_cams):
                self._put_block(self._empty_frame, cdx, FrameIndexCategory.EOF_OFFLINE_PROCESSING)

    def _feed_intersession_analysis_execute(self, project, wait_stop_recorded):
        cams = (project.camera_1, project.camera_2)
        n_cams = len(cams)
        cams_paths = [
            tuple(map(Path, project.get_video_path(name=cam, allow_overwrite=True)))
            for cam in cams
        ]
        tot_skipped_frames = 0

        def check_correct_status():
            if self._live_requested:
                raise InferenceIncorrectStatus("live requested while feeding")
            if self._interrupted:
                raise InferenceIncorrectStatus("feed interrupted")
        #
        perf_timeout = get_perf_now() + 10  # intersession_wait_time is too small
        # the pose process and data monitor thread have some delay between them,
        # sometimes up to several seconds (4-5).
        # wait that we get the event from monitor data queue closing its write side to live files:
        if wait_stop_recorded:
            logger.debug("waiting stop_recorded on %s", self._stop_recorded)
            while not self._stop_recorded.wait(0.1):
                if get_perf_now() > perf_timeout:
                    raise RuntimeError("timeout waiting for intersession stop_recorded event")
                check_correct_status()
            self._stop_recorded.clear()
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
        p_before = get_perf_now()
        perf_timeout = p_before + 10
        count_loops = 0
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
            count_loops += 1
            if get_perf_now() > perf_timeout:
                raise RuntimeError(f"timeout waiting for intersession video files {video_paths}")
            time.sleep(0.1)  # overkill to immediately retry

        logger.debug("Waited %.1fs (count_loops=%s) for video files ready",
                     get_perf_now() - p_before, count_loops)

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
                    lst[2][0]  # the third row contains the associated frame index in h5 file ([0] to extract it from array)
                    for lst in h5py.File(
                        project.get_intersession_pose_path(cam, suffix="_live")
                    )["df_with_missing"]["table"]
                ]
                for cdx, cam in enumerate(cams)
            ]
            if cams_already_processed_idx_list != cams_already_processed_idx2:
                for cdx in range(2):
                    set_diff = set(cams_already_processed_idx_list[cdx]) - set(cams_already_processed_idx2[cdx])
                    logger.warning("Unexpected difference in processed cams frames index vs processed h5: cdx=%s len1=%s len2=%s diff=%s",
                                   cdx, len(cams_already_processed_idx_list), len(cams_already_processed_idx2), set_diff)

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
                    self._put_block(self._empty_frame, cdx, FrameIndexCategory.PADDING)
                else:
                    if not self._put_intersession_frame(cam_capture, cdx, cams_frame_idx[cdx]):
                        all_read[cdx] = True
                        self._put_block(self._empty_frame, cdx, FrameIndexCategory.PADDING)
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

        if __debug__ and _local_do_debug:
            for cdx in range(n_cams):
                with open(str(cams_paths[cdx][-1]) + "_sent_to_processing.txt", "w") as fh:
                    fh.write("\n".join(map(str, chain(frames_idx_sent[cdx], [""]))))

        # total frame count: taking the min of all saved videos frame count:
        # intersession_block.frame_count = min(videos_frame_count.values())

        # ProcessLiveWhenReady is async vs EOF_OFFLINE_PROCESSING just send before
        # it's not anymore actually used by pose process, but we still deliver it, for log purpose mainly.
        # self._send_message(InferenceCommandMessageKind.ProcessLiveWhenReady)
        # TODO

        logger.success("passed %s frames per camera frame_count=%s ; "
                       "tot_skipped_frames=%s cams_frame_idx=%s cams_sent_frame_count=%s",
                       frame_idx, min(videos_frame_count.values()),
                       tot_skipped_frames, cams_frame_idx, cams_sent_frame_count)
