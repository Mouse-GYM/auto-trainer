import collections
import csv
import ctypes
import dataclasses
import math
import statistics
import os
import threading
import time
from multiprocessing.sharedctypes import Synchronized
from pathlib import Path
from datetime import datetime
from typing import Deque, Tuple, List

import cv2
import numpy
import numpy as np

from autotrainer.core import ValueHolderDescriptor
from autotrainer.core.configuration.presence_detection_configuration import PresenceDetectionConfig
from autotrainer.core.project.project_info import ProjectInfo
from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.multiproc import get_mp_ctx


logger = get_verbose_logger(__name__)


@dataclasses.dataclass
class PresenceDetectionAttrs:

    pc_threshold = ValueHolderDescriptor()
    # the fg mask sum (as percent vs max(100)) threshold above which the presence is assumed
    _pc_threshold: Synchronized = None

    pc_high_exclude_threshold = ValueHolderDescriptor()
    # but if above this exclude threshold then don't trigger.
    _pc_high_exclude_threshold: Synchronized = None

    mask_lower_zero = ValueHolderDescriptor()
    _mask_lower_zero: Synchronized = None
    # zero all values in the frame below this value

    max_delay_skip_threshold = ValueHolderDescriptor()
    _max_delay_skip_threshold: Synchronized = None
    # remove frames older than this only. all frames within this delay will be taken into account

    # could be todo: allow compare with one frame with the xth previous one (second, or third, for instance),
    #  not only the very next one, that would/could allow detect slower movement/presence

    last_absence_start_perf_c = ValueHolderDescriptor()
    _last_absence_start_perf_c: Synchronized = None

    last_presence_start_perf_c = ValueHolderDescriptor()
    _last_presence_start_perf_c: Synchronized = None

    presence_detected = ValueHolderDescriptor()
    _presence_detected: Synchronized = None

    movement_detected = ValueHolderDescriptor()
    _movement_detected: Synchronized = None

    pc_sum = ValueHolderDescriptor()
    _pc_sum: Synchronized = None

    def __post_init__(self):
        ctx = get_mp_ctx()
        if  self._pc_threshold is None:
            self._pc_threshold = ctx.Value(ctypes.c_double, PresenceDetectionConfig.pc_threshold)
        if self._pc_high_exclude_threshold is None:
            self._pc_high_exclude_threshold = ctx.Value(ctypes.c_double, PresenceDetectionConfig.pc_high_exclude_threshold)
        if self._mask_lower_zero is None:
            self._mask_lower_zero = ctx.Value(ctypes.c_double, PresenceDetectionConfig.mask_lower_zero)
        if self._max_delay_skip_threshold is None:
            self._max_delay_skip_threshold = ctx.Value(ctypes.c_double, PresenceDetectionConfig.max_delay_skip_threshold)
        if self._last_absence_start_perf_c is None:
            self._last_absence_start_perf_c = ctx.Value(ctypes.c_double, -math.inf)
        if self._last_presence_start_perf_c is None:
            self._last_presence_start_perf_c = ctx.Value(ctypes.c_double, -math.inf)
        if self._presence_detected is None:
            self._presence_detected = ctx.Value(ctypes.c_bool, False)
        if self._movement_detected is None:
            self._movement_detected = ctx.Value(ctypes.c_bool, False)
        if self._pc_sum is None:
            self._pc_sum = ctx.Value(ctypes.c_double, 0)

    def to_config(self) -> PresenceDetectionConfig:
        return PresenceDetectionConfig(**{
            field.name: getattr(self, field.name)
            for field in dataclasses.fields(PresenceDetectionConfig)
        })

    def load_config(self, cfg: PresenceDetectionConfig):
        for field in dataclasses.fields(cfg):
            setattr(self, field.name, getattr(cfg, field.name))


class VideoDetection(threading.Thread):

    def __init__(self, project_info: ProjectInfo, detection_attrs: PresenceDetectionAttrs):
        self._project_info = project_info
        self._attrs = detection_attrs
        self._stop_requested = False
        # using a dequeue with 8 entries,
        # NB: is thread-safe for append/popleft. see (c)python doc.
        self._next_frames: Deque[Tuple[float, numpy.ndarray]] = collections.deque(maxlen=10)
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

    def update_frame(self, when: float, frame: numpy.ndarray):
        if not self._got_first_frame:
            self._got_first_frame = True
            perf_now = time.perf_counter()
            self._attrs.last_absence_start_perf_c = perf_now
            self._attrs.last_presence_start_perf_c = perf_now
            # this allows to get good measurement from monitors using the detection result(s)
        self._next_frames.append((when, frame))

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
        prev_gray_frame = prev_when = None
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
                when_nanos, frame = self._next_frames.popleft()
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
            save_prev_when = prev_when
            save_prev_gray_frame = prev_gray_frame
            prev_when = when
            prev_gray_frame = gray_frame
            if save_prev_gray_frame is None:
                # (re)init frame
                continue
            if when - save_prev_when >= attrs.max_delay_skip_threshold:
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
                    Index=when_nanos,
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
                attrs.presence_detected = is_detected
                if is_detected:
                    attrs.last_presence_start_perf_c = perf_now
                else:
                    attrs.last_absence_start_perf_c = perf_now
                prev_gray_frame = None  # this will make us to get the following necessary next frames for next check
            if show_report:
                prev_pc_values.append((pc_normalized, pc_unnormalized))
                processed_times.append(time.perf_counter() - loop_start_perf_now)
        # end while not self._stop_requested
