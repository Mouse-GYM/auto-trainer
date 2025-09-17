import collections
import csv
import ctypes
import dataclasses
import math
import multiprocessing
import os
import threading
import time
from operator import attrgetter
from pathlib import Path
from typing import Deque, Tuple, Optional

import cv2
import numpy

from autotrainer.core import ProjectInfo
from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.multiproc import get_mp_ctx


logger = get_verbose_logger(__name__)


def _make_prop_value(name):
    priv_name = f"_{name}"
    def getter(self):
        value_holder = getattr(self, priv_name)
        return value_holder.value
    getter.__name__ = name
    def setter(self, value):
        value_holder = getattr(self, priv_name)
        value_holder.value = value
    setter.__name__ = name
    return property(getter, setter)


@dataclasses.dataclass
class PresenceDetectionAttrs:

    presence_sum_percent_threshold: float = 5
    # the fg mask sum (as percent vs max(100)) threshold above which the presence is assumed
    # todo: we should have a max_threshold that if over we don't consider the result,
    #  this would skip when light is turned ON/OFF for instance.

    mask_lower_zero: float = 0.1
    # zero all values in the frame below this value

    max_delay_skip_threshold: float = 0.075   # >= 0.033 ms
    # if 2 consecutive processed frames have more than that delay between them,
    # then skip oldest and continue with most recent

    # could be todo: allow compare with one frame on to the xth following one (second, or third, for instance),
    #  not only the very next one, that would/could allow detect slower movement/presence

    _last_absence_start_perf_c: multiprocessing.Value = None  # noqa
    _last_presence_start_perf_c: multiprocessing.Value = None  # noqa
    _presence_detected: multiprocessing.Value = None  # noqa
    _movement_detected: multiprocessing.Value = None  # noqa
    _pc_sum: multiprocessing.Value = None  # noqa

    def __post_init__(self):
        ctx = get_mp_ctx()
        if self._last_absence_start_perf_c is None:
            self._last_absence_start_perf_c = ctx.Value(ctypes.c_double, -math.inf)
        if self._last_presence_start_perf_c is None:
            self._last_presence_start_perf_c = ctx.Value(ctypes.c_double, -math.inf)
        if self._presence_detected is None:
            self._presence_detected = ctx.Value(ctypes.c_bool)
        if self._movement_detected is None:
            self._movement_detected = ctx.Value(ctypes.c_bool)
        if self._pc_sum is None:
            self._pc_sum = ctx.Value(ctypes.c_float)

    # todo: use a class descriptor (allow to not repeat/have to specify the attribute name on the rhs)
    last_absence_start_perf_c = _make_prop_value("last_absence_start_perf_c")
    last_presence_start_perf_c = _make_prop_value("last_presence_start_perf_c")
    presence_detected = _make_prop_value("presence_detected")
    movement_detected = _make_prop_value("movement_detected")
    pc_sum = _make_prop_value("pc_sum")


class VideoDetection(threading.Thread):

    def __init__(self, project_info: ProjectInfo, detection_attrs: PresenceDetectionAttrs):
        self._project_info = project_info
        self._attrs = detection_attrs
        self._stop_requested = False
        # using a dequeue with 8 entries,
        # NB: is thread-safe for append/popleft. see (c)python doc.
        self._next_frames: Deque[Tuple[float, numpy.ndarray]] = collections.deque(maxlen=8)
        # not sure using a simple thread queue.Queue is not as good, possibly better (can wait on it)
        self._prev_frame = None
        self._prev_when = None
        self._csv_header = ["Time", "Index", "PercentSum", "Presence", "Motion"]
        self._file_info = None
        self._csv_writer = None
        self._csv_writer_fh = None
        super().__init__(name="PresenceDetection")

    def cancel(self):
        self._stop_requested = True

    def update_frame(self, when: float, frame: numpy.ndarray):
        self._next_frames.append((when, frame))

    def _check_path(self):
        csv_file_info = self._project_info.get_webcam_presence_file()
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
        prev_frame = prev_when = None
        prev_detected = None  # attrs.presence_detected.value
        prev_pc_sum = None
        row_dict = dict.fromkeys(self._csv_header)
        next_log_report = time.perf_counter() + 5
        processed_count = 0
        timeout_count = 0
        expired_count = 0
        delay_report = int(os.getenv("PRES_DET_DELAY_REPORT", "180"))
        prev_pc_values = []
        while not self._stop_requested:
            perf_now = time.perf_counter()
            if perf_now >= next_log_report or len(prev_pc_values) > 30:
                logger.debug("video presence detection: %s ; processed=%.1f/s timeout=%.1f/s expired_count=%.1f/s ; values=%s",
                             [w for w, _ in self._next_frames], processed_count / delay_report, timeout_count / delay_report,
                             expired_count / delay_report, prev_pc_values)
                next_log_report = perf_now + delay_report
                processed_count = timeout_count = expired_count = 0
                prev_pc_values.clear()
            try:
                when_nanos, frame = self._next_frames.popleft()
            except IndexError:
                time.sleep(0.03)  # current producer is 30 fps.
                timeout_count += 1
                continue
            #
            when = when_nanos / 1e9  # convert to second timestamp
            #
            if frame.ndim > 2:
                gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            else:
                gray_frame = frame
            save_prev_when = prev_when
            save_prev_frame = prev_frame
            prev_when = when
            prev_frame = gray_frame
            if save_prev_frame is None:
                # (re)init frame
                continue
            if when - save_prev_when >= attrs.max_delay_skip_threshold:
                expired_count += 1
                continue
            # work on frame
            processed_count += 1
            fg_mask = cv2.absdiff(save_prev_frame, gray_frame)
            fg_mask[fg_mask < attrs.mask_lower_zero] = 0
            tot_sum = numpy.sum(fg_mask)
            # use round with 0 decimal place,
            # this allows to limit/lower the nbr of updates we do to the shared value
            pc_tot_sum = round(100 * tot_sum / (fg_mask.size * (255 ** fg_mask.itemsize)),
                               0)
            if pc_tot_sum != prev_pc_sum:
                attrs.pc_sum = pc_tot_sum
                prev_pc_sum = pc_tot_sum
                prev_pc_values.append(pc_tot_sum)
            is_detected = pc_tot_sum >= attrs.presence_sum_percent_threshold
            if is_detected != prev_detected:
                logger.verbose("presence detected: %.2f", pc_tot_sum)
                prev_detected = is_detected
                attrs.presence_detected = is_detected
                perf_now = time.perf_counter()
                if is_detected:
                    attrs.last_presence_start_perf_c = perf_now
                else:
                    attrs.last_absence_start_perf_c = perf_now
                prev_frame = None  # this will make us to get the following 2 next frames for next check
            self._check_path()
            csv_writer = self._csv_writer
            if csv_writer is not None:
                row_dict.update(
                    Time=when,
                    Index=when_nanos,
                    PercentSum=pc_tot_sum,
                    Presence=int(is_detected),
                    Motion=0,  # TODO
                )
                csv_writer.writerow(row_dict)
        # end while not self._stop_requested
