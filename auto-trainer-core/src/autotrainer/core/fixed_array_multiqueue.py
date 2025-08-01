import ctypes
import logging
import multiprocessing
import time

from multiprocessing import RawArray, Value
from multiprocessing.context import BaseContext
from typing import Tuple, List, Optional

import numpy

from autotrainer.core import get_verbose_logger
from autotrainer.core.fixed_array_queue import BufferResult
from autotrainer.core.message import FrameIndexCategory
from autotrainer.core.multiproc import get_mp_ctx

logger = get_verbose_logger(__name__)


class FixedArrayMultiQueue:
    """
    Alternative to multiprocessing.Queue.

    FixedArrayMultiQueue is an alternative to multiprocessing.Queue that
    * Explicitly queues batches of 2D data from one or more sources
    * Pre-allocates RawArray instances to hold the data for performance

    The class does not share the exact put/get_xyz interface of the standard Queue classes as it is not a drop-in
    replacement for Queue in terms of behavior.
    """
    def __init__(self,
                 depth: int,
                 cam_count: int,
                 frames_per_camera: int,
                 shape: Tuple[int, int],
                 *,
                 primary: int = 0,
                 name: str="noname",
                 mp_ctx: Optional[BaseContext] = None,
                 ):
        """
        :param depth: queue length before discarding old data if consumers can not keep up
        :param cam_count: number of sources (e.g., cameras) providing 2D data (frames)
        :param frames_per_camera: number of frames per source
        :param shape: size of each frame
        :param primary: indicates which source (index) defines when frames_per_camera is met and a buffer rotates
        """
        if mp_ctx is None:
            mp_ctx = get_mp_ctx()

        self._name = name
        self._barrier = mp_ctx.Barrier(cam_count)
        self._semaphore = mp_ctx.Semaphore(cam_count)
        for _ in range(cam_count):
            self._semaphore.acquire()  # pre-acquire all
        self._event = mp_ctx.Event()
        # indexing: [buffer][camera][batch_frame]
        self._buffers: List[List[List[RawArray]]] = []

        self._depth = depth
        self._cam_count = cam_count
        self._frames_per_camera = frames_per_camera
        self._primary = primary

        self._buffer_index = [0] * self._cam_count
        self._batch_index = [0] * self._cam_count
        self._read_index = 0

        self._shape = shape
        self._byte_count = shape[0] * shape[1]  # 1 frame byte count, no RGB, only 8-bit gray.

        self._buff_views = []
        for idx in range(self._depth):
            buffer = []
            view = []
            for cdx in range(self._cam_count):
                cam_buffer = []
                cam_view = []
                for bdx in range(self._frames_per_camera):
                    # TODO: could use a single rawarray per camera
                    cam_buffer.append(mp_ctx.RawArray(ctypes.c_ubyte, self._byte_count))
                buffer.append(cam_buffer)
                view.append(cam_view)

            self._buffers.append(buffer)
            self._buff_views.append(view)

        self._is_dirty = [
            # 1 shared array to mark frames in shared mem as ready or not.
            # if value true: means "dirty" means has valid frame in it.
            mp_ctx.RawArray(ctypes.c_bool, self._depth * self._frames_per_camera)
            for _ in range(self._cam_count)
        ]

        # a single shared array for all frames indices of all cameras:
        self._frame_indices = mp_ctx.RawArray(ctypes.c_int64, self._depth * self._frames_per_camera * self._cam_count)

        self._frame_indexing: List[int] = list(numpy.repeat(range(self._frames_per_camera), self._cam_count))
        self._camera_indexing: List[int] = list(numpy.tile(range(self._cam_count), self._frames_per_camera))

        self._next_counts_log_time = time.time()
        self._overflow_count = 0
        self._put_count = 0

    def __str__(self):
        return f"{self.__class__.__name__}({self._name!r})"

    @property
    def barrier(self) -> multiprocessing.Barrier:
        return self._barrier

    @property
    def semaphore(self) -> multiprocessing.Semaphore:
        return self._semaphore

    @property
    def event(self):
        return self._event

    @property
    def depth(self):
        return self._depth

    @property
    def camera_count(self):
        return self._cam_count

    @property
    def frames_per_camera(self):
        return self._frames_per_camera

    @property
    def batch_size(self):
        return self.camera_count * self.frames_per_camera

    @property
    def shape(self):
        return self._shape

    @property
    def buffer_index(self) -> int:
        return self._buffer_index[0]

    def reset_writer(self, cam_idx: int):
        self._buffer_index[cam_idx] = 0
        self._batch_index[cam_idx] = 0
        zero = memoryview(bytes([0] * self._depth * self._frames_per_camera)).cast("B")
        memoryview(self._is_dirty[cam_idx]).cast("B")[:] = zero
        self._overflow_count = 0
        self._put_count = 0
        logger.debug("%s: cam-%s writer index reset to 0", self, cam_idx)

    def reset_reader(self):
        self._read_index = 0
        logger.debug("%s: read_index reset to 0", self)

    def is_frame_ready(self, frame_idx):
        frame_idx = frame_idx % (self._depth * self._frames_per_camera)
        for cdx in range(self._cam_count):
            if not self._is_dirty[cdx][frame_idx]:
                return False
        return True

    def get_all_cam_max_frame_idx(self, camera_idx: int):
        b = numpy.frombuffer(
            memoryview(self._frame_indices).cast("B"), "int64", len(self._frame_indices)
        ).reshape((self._cam_count, self._depth, self._frames_per_camera))
        all_max = b.max()
        cam_max = b[camera_idx].max()
        return all_max, cam_max

    def get_cam_frame_idx(self, camera_idx: int):
        b = numpy.frombuffer(
            memoryview(self._frame_indices).cast("B"), "int64", len(self._frame_indices)
        ).reshape((self._cam_count, self._depth, self._frames_per_camera))[camera_idx]
        return b.max()

    def get_max_frame_idx(self):
        b = numpy.frombuffer(
            memoryview(self._frame_indices).cast("B"), "int64", len(self._frame_indices)
        ).reshape((self._cam_count, self._depth, self._frames_per_camera))
        return b.max()

    def put(self, content: numpy.ndarray, camera: int, frame_idx: Optional[int], allow_overflow: bool = True) -> BufferResult:
        buffer_index = self._buffer_index[camera]  # 0 ... up to depth - 1
        batch_index = self._batch_index[camera]  # 0 ... up to frames per camera - 1
        dirty_idx = buffer_index * self._frames_per_camera + batch_index
        is_overflow = self._is_dirty[camera][dirty_idx]
        t = time.time()
        if t > self._next_counts_log_time:
            self._next_counts_log_time += 10
            logger.debug("%s[%s]: put=%s overflow=%s", self, camera, self._put_count, self._overflow_count)
            self._put_count = self._overflow_count = 0
        if is_overflow:
            self._overflow_count += 1
            if not allow_overflow:
                return BufferResult.Overflow
            # NB: doing overwrite of a dirty bucket as was done previously is NOT good:
            # the reader could be reading that same bucket at the same time...
            # getting totally mixed data from different frames.
            # we could overwrite on the previous bucket though,
            # given that would be the lowest chance of the reader to have reached it.
            # at the moment deciding to NOT overwrite: so to not induce this extra "overload" while the reader
            # is already slow/far behind.
            # the caller of this function has to check its return code/value to decide to retry or not.
            return BufferResult.Overflow
            #
        cur_view = memoryview(self._buffers[buffer_index][camera][batch_index]).cast("B")
        # reshape does not copy if not necessary
        cur_view[:] = content.reshape(-1)
        if frame_idx is not None:
            b = numpy.frombuffer(
                memoryview(self._frame_indices).cast("B"), "int64", len(self._frame_indices)
            ).reshape((self._cam_count, self._depth, self._frames_per_camera))[camera]
            b[buffer_index][batch_index] = frame_idx
        self._put_count += 1
        self._is_dirty[camera][dirty_idx] = True
        #
        batch_index = self._batch_index[camera] = (batch_index + 1) % self._frames_per_camera
        if batch_index == 0:
            self._buffer_index[camera] = (1 + buffer_index) % self._depth

        return BufferResult.Ok if not is_overflow else BufferResult.Overflow

    def get_output(self, output: numpy.ndarray, frames_indices: Optional[numpy.ndarray] = None):
        """Get the next available "output" : i.e: 1 batch of frames_per_camera * nbr_cameras
        """
        read_idx_value = self._read_index
        # lookup up to frames_per_camera:
        if not self.is_frame_ready(read_idx_value * self._frames_per_camera + self._frames_per_camera - 1):
            return False
        buffer = self._buffers[read_idx_value]
        for idx, cdx in enumerate(self._camera_indexing):
            v = numpy.frombuffer(
                buffer[cdx][self._frame_indexing[idx]], "uint8", self._byte_count
            ).reshape(self.shape)
            # NB: current predict model expects an RGB frame,
            # we have so to copy 3 times the current grey image/frame into the 3 planes:
            # for fn in range(3):
            #     output[idx, :, :, fn] = v
            # we do that after setting dirty back to 0
            output[idx, :, :, 0] = v

        if frames_indices is not None:
            # copy frames indices
            frames_indices[:, :] = numpy.frombuffer(
                memoryview(self._frame_indices).cast("B"), "int64", len(self._frame_indices)
            ).reshape(
                (self._cam_count, self._depth, self._frames_per_camera)
            )[:, read_idx_value, :]

        dx = read_idx_value * self._frames_per_camera
        for cdx in range(self._cam_count):
            self._is_dirty[cdx][dx : dx + self._frames_per_camera] = [False] * self._frames_per_camera

        # make the copy for rgb after having unset dirty
        for idx, cdx in enumerate(self._camera_indexing):
            for fn in (1, 2):
                output[idx, :, :, fn] = output[idx, :, :, 0]

        # don't forget to:
        self._read_index = (read_idx_value + 1) % self._depth
        return True

    def put_frame_index_category(self, frame, frame_idx: int, *, timeout: float = 5):
        t_end = time.time() + timeout
        for cdx in range(self._cam_count):
            for _ in range(self._frames_per_camera):
                while self.put(frame, cdx, frame_idx, allow_overflow=False) != BufferResult.Ok:
                    if time.time() > t_end:
                        raise RuntimeError(f"cam-{cdx}: timeout waiting space in array multiqueue")
                    time.sleep(0.005)

    def pad_cur_batch(
        self,
        cam_idx: int,
        frame: numpy.ndarray,
        *,
        timeout: float = 5,
        pad_idx: int = FrameIndexCategory.PADDING,
    ) -> bool:
        """Return True if added some pad, False otherwise"""
        t_end = time.time() + timeout
        cur_batch_idx = self._batch_index[cam_idx]
        if cur_batch_idx == 0:
            return False
        tot_to_pad = self._frames_per_camera - cur_batch_idx
        logger.verbose("padding cam-%s with %s %s frames", cam_idx, tot_to_pad, pad_idx)
        for _ in range(tot_to_pad):
            while self.put(frame, cam_idx, pad_idx, allow_overflow=False) != BufferResult.Ok:
                if time.time() > t_end:
                    raise RuntimeError(f"timeout waiting space for cam-{cam_idx} in {self}")
                time.sleep(0.005)
        return True
