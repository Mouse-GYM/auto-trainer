import collections
import csv
import ctypes
import dataclasses
import multiprocessing
import threading
import time
from pathlib import Path
from typing import Deque, Tuple

import cv2
import numpy

from autotrainer.core import ProjectInfo
from autotrainer.core.logging import get_verbose_logger
from autotrainer.core.multiproc import get_mp_ctx


logger = get_verbose_logger(__name__)


@dataclasses.dataclass
class PresenceDetectionAttrs:

    presence_sum_percent_threshold: float = 5
    # the fg mask sum (as percent vs max) threshold above which the presence is assumed

    mask_lower_zero: float = 0.1
    # zero all values in the frame below this value

    presence_detected: multiprocessing.Value = None
    movement_detected: multiprocessing.Value = None
    pc_sum: multiprocessing.Value = None

    def __post_init__(self):
        ctx = get_mp_ctx()
        if self.presence_detected is None:
            self.presence_detected = ctx.Value(ctypes.c_bool)
        if self.movement_detected is None:
            self.movement_detected = ctx.Value(ctypes.c_bool)
        if self.pc_sum is None:
            self.pc_sum = ctx.Value(ctypes.c_float)


class VideoDetection(threading.Thread):

    def __init__(self, project_info: ProjectInfo, detection_attrs: PresenceDetectionAttrs):
        self._project_info = project_info
        self._attrs = detection_attrs
        self._stop_requested = False
        self._next_frames: Deque[Tuple[float, numpy.ndarray]] = collections.deque(maxlen=60)
        self._prev_frame = None
        self._prev_when = None
        self._csv_header = ["Time", "Index", "Presence", "Motion"]
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
            self._csv_writer_fh = open(csv_file_info.file, "a")
            self._csv_writer = csv.DictWriter(self._csv_writer_fh, self._csv_header)
            if not prev_exist:
                self._csv_writer.writeheader()
        self._file_info = csv_file_info

    def run(self):
        attrs = self._attrs
        prev_frame = prev_when = None
        prev_detected = attrs.presence_detected.value
        row_dict = dict.fromkeys(self._csv_header)

        while not self._stop_requested:
            try:
                when, frame = self._next_frames.popleft()
            except IndexError:
                time.sleep(0.05)
                continue
            if frame.ndim > 2:
                gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            else:
                gray_frame = frame
            if prev_frame is not None:
                # work on frame
                fg_mask = cv2.absdiff(prev_frame, gray_frame)
                fg_mask[fg_mask < attrs.mask_lower_zero] = 0
                tot_sum = numpy.sum(fg_mask)
                pc_tot_sum = 100 * tot_sum / (fg_mask.size * (255 ** fg_mask.itemsize))
                attrs.pc_sum.value = pc_tot_sum
                is_detected = pc_tot_sum >= attrs.presence_sum_percent_threshold
                if is_detected != prev_detected:
                    attrs.presence_detected.value = is_detected
                prev_detected = is_detected
                self._check_path()
                csv_writer = self._csv_writer
                if csv_writer is not None:
                    row_dict.update(
                        Time=when / 1e9,
                        Index=when,
                        Presence=int(is_detected),
                        Motion=0,  # TODO
                    )
                    csv_writer.writerow(row_dict)
            prev_frame = gray_frame
            prev_when = when
        # end while not self._stop_requested
        fh = self._csv_writer_fh
        if fh is not None:
            fh.flush()
            fh.close()
