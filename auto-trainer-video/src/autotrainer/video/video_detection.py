import collections
import csv
import math
import os
import statistics
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Deque, Tuple, List

import cv2
import numpy
import numpy as np

from autotrainer.core import ProjectInfo, get_perf_now
from autotrainer.core.video_detection import PresenceDetectionAttrs


class VideoDetection(threading.Thread):

    def __init__(self, project_info: ProjectInfo, detection_attrs: PresenceDetectionAttrs):
        self._project_info = project_info
        self._attrs = detection_attrs
        self._stop_requested = False
        # using a deque with 8 entries,
        # NB: is thread-safe for append/popleft. see (c)python doc.
        self._next_frames: Deque[Tuple[float, numpy.ndarray, float]] = collections.deque(maxlen=10)
        # not sure using a simple thread queue.Queue is not as good, possibly better (can wait on it)
        self._prev_frame = None
        self._prev_when = None
        self._csv_header = ["Time", "Index", "PercentSum", "Motion"]
        self._file_info = None
        self._csv_writer = None
        self._csv_writer_fh = None
        self._got_first_frame = False
        super().__init__(name="PresenceDetection", daemon=True)

    def cancel(self):
        self._stop_requested = True

    def update_frame(self, when: float, frame: numpy.ndarray, perf_c: float):
        if not self._got_first_frame:
            self._got_first_frame = True
            perf_now = get_perf_now()
            self._attrs.last_absence_start_perf_c = perf_now
            self._attrs.last_presence_start_perf_c = perf_now
            # this allows to get good measurement from monitors using the detection result(s)
        self._next_frames.append((when, frame, perf_c))

    def _check_path(self):
        csv_file_info = self._project_info.get_webcam_presence_file(when=datetime.now())
        if csv_file_info == self._file_info:
            return
        if self._csv_writer_fh is not None:
            self._csv_writer_fh.flush()
            self._csv_writer_fh.close()
        if csv_file_info is None:
            self._csv_writer_fh = self._csv_writer = None
        else:
            f_path = Path(csv_file_info.file)
            logger.verbose("Switching to %s", f_path)
            prev_exist = f_path.is_file() and f_path.exists() and f_path.stat().st_size > 0
            self._csv_writer_fh = f_path.open("a")
            self._csv_writer = csv.DictWriter(self._csv_writer_fh, self._csv_header)
            if not prev_exist:
                self._csv_writer.writeheader()
        self._file_info = csv_file_info

    def run(self):
        try:
            self._run()
        finally:
            fh = self._csv_writer_fh
            if fh is not None:
                fh.flush()
                fh.close()

    def _run(self):
        attrs = self._attrs
        prev_pc_threshold = attrs.pc_threshold
        prev_gray_frame = prev_frame_perf_c = None
        prev_detected = None  # attrs.presence_detected.value
        prev_pc_sum = None
        row_dict = dict.fromkeys(self._csv_header)
        next_log_report = time.perf_counter() + 5
        processed_count = 0
        expired_count = 0
        show_report = os.getenv("PRESENCE_DETECTION_SHOW_REPORT", "").lower() in {"y", "yes", "true", "1"}
        delay_report = int(os.getenv("PRES_DET_DELAY_REPORT", "180"))
        processed_times: List[float] = []
        prev_pc_values = []
        hist_values: List[Tuple[float, np.ndarray, float, float]] = []
        #                       when, gray_frame, pc_norm, pc_unnorm
        def update_hist(w, new_frame, pc_norm, pc_unnorm):
            idx = len(hist_values) - 1
            while idx >= 0:
                w2 = hist_values[idx][0]
                if w - w2 >= attrs.max_delay_skip_threshold:
                    del hist_values[:idx + 1]  # need + 1 with range (:+1)
                    break
                idx -= 1
            hist_values.append((w, new_frame, pc_norm, pc_unnorm))
        #
        last_log_report = time.perf_counter()
        while not self._stop_requested:
            perf_now = time.perf_counter()
            loop_start_perf_now = perf_now
            if show_report and perf_now >= next_log_report:
                actual_delay = perf_now - last_log_report
                logger.debug("video presence detection: %s, frame/s=%.1f mean_proc_time=%.3f ; expired_count=%.1f/s ; values=%s",
                             prev_pc_values[-1][0] if len(prev_pc_values) > 0 else math.nan,
                             processed_count / actual_delay,
                             statistics.mean(processed_times) if processed_times else math.nan,
                             expired_count / actual_delay, prev_pc_values)
                last_log_report = perf_now
                next_log_report = perf_now + delay_report
                processed_count = expired_count = 0
                prev_pc_values.clear()
                processed_times.clear()
            try:
                when_nanos, frame, frame_perf_c = self._next_frames.popleft()
            except IndexError:
                time.sleep(0.003)  # current producer is 30 fps. let's use very smallish sleep
                continue
            #
            when = when_nanos / 1e9  # convert to second timestamp
            #
            if frame.ndim > 2:
                gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            else:
                gray_frame = frame
            # given we divide by fg_mask.size below to calculate a % value,
            # it does not really matter to rescale to any size:
            # gray_frame = cv2.resize(gray_frame, (256, 256), interpolation=cv2.INTER_LINEAR)
            save_prev_perf_c = prev_frame_perf_c
            save_prev_gray_frame = prev_gray_frame
            prev_frame_perf_c = when
            prev_gray_frame = gray_frame
            if save_prev_gray_frame is None:
                # (re)init frame
                continue
            if frame_perf_c - save_prev_perf_c >= attrs.max_delay_skip_threshold:
                expired_count += 1
                continue
            # work on frame
            cur_pc_threshold = attrs.pc_threshold
            if cur_pc_threshold != prev_pc_threshold:
                logger.debug("Using new pc_threshold: %s", cur_pc_threshold)
                prev_pc_threshold = cur_pc_threshold
            processed_count += 1
            fg_mask = cv2.absdiff(save_prev_gray_frame, gray_frame)
            fg_mask[fg_mask < attrs.mask_lower_zero] = 0
            tot_sum_unnormalized = numpy.sum(fg_mask)
            fg_mask[fg_mask >= attrs.mask_lower_zero] = 1
            tot_sum_normalized = numpy.sum(fg_mask)
            pc_normalized = 100 * tot_sum_normalized / fg_mask.size
            pc_normalized = round(pc_normalized, 1)
            # NB: not using the unnormalized value atm:
            pc_unnormalized = (100 * tot_sum_unnormalized) / (fg_mask.size * 8 ** fg_mask.itemsize)
            pc_unnormalized = round(pc_unnormalized, 1)
            update_hist(when, gray_frame, pc_normalized, pc_unnormalized)
            if pc_normalized != prev_pc_sum:
                # NB: we have:
                # fg_mask.size == 2073600 and fg_mask.itemsize == 1
                if __debug__:
                    if pc_normalized is None or prev_pc_sum is None or round(pc_normalized, 0) != round(prev_pc_sum, 0):
                        logger.spam("pc_norm=%.2f pc_unnorm=%.2f hist=%s",
                                       pc_normalized, pc_unnormalized, [(d1, d2, d3) for d1, _, d2, d3 in hist_values])
                attrs.pc_sum = pc_normalized
                prev_pc_sum = pc_normalized
            #
            cur_exclude_threshold = attrs.pc_high_exclude_threshold
            is_detected = (
                cur_pc_threshold <= pc_normalized < cur_exclude_threshold
            )
            self._check_path()
            csv_writer = self._csv_writer
            if csv_writer is not None:
                row_dict.update(
                    Time=when,
                    Index=int(frame_perf_c * 1e9),  # to be consistent with others csv data files using Time/Index
                    PercentSum=pc_normalized,
                    Motion=int(is_detected),
                )
                csv_writer.writerow(row_dict)
            # now use everything available in hist_values:
            is_detected = (
                any(pc_normalized >= cur_pc_threshold
                    for _, _, pc_normalized, _ in hist_values)
            ) and not (
                any(pc_normalized >= cur_exclude_threshold
                    for _, _, pc_normalized, _ in hist_values)
            )
            if is_detected != prev_detected:
                logger.debug("presence detected: %.1f - %.1f ; hist=%s",
                               pc_normalized, pc_unnormalized, [(d1, d2, d3) for d1, _, d2, d3 in hist_values])
                prev_detected = is_detected
                with attrs.lock:  # use lock to really ensure consistency
                    attrs.presence_detected = is_detected
                    if is_detected:
                        attrs.last_presence_start_perf_c = frame_perf_c
                    else:
                        attrs.last_absence_start_perf_c = frame_perf_c
                prev_gray_frame = None  # this will make us to get the following necessary next frames for next check
            if show_report:
                prev_pc_values.append((pc_normalized, pc_unnormalized))
                processed_times.append(time.perf_counter() - loop_start_perf_now)
        # end while not self._stop_requested
