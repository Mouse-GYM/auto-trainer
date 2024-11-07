import ctypes
import logging

from multiprocessing import RawArray, Value

import numpy

from autotrainer.core.fixed_array_queue import BufferResult

logger = logging.getLogger(__name__)


class FixedArrayMultiQueue:
    """
    Alternative to multiprocessing.Queue.

    FixedArrayMultiQueue is an alternative to multiprocessing.Queue that
    * Explicitly queues batches of 2D data from one or more sources
    * Pre-allocates RawArray instances to hold the data for performance

    The class does not share the exact put/get_xyz interface of the standard Queue classes as it is not a drop-in
    replacement for Queue in terms of behavior.
    """
    def __init__(self, depth: int, cam_count: int, frames_per_camera: int, shape: (int, int), primary: int = 0):
        """
        :param depth: queue length before discarding old data if consumers can not keep up
        :param cam_count: number of sources (e.g., cameras) providing 2D data (frames)
        :param frames_per_camera: number of frames per source
        :param shape: size of each frame
        :param primary: indicates which source (index) defines when frames_per_camera is met and a buffer rotates
        """
        # indexing: [buffer][camera][batch_frame]
        self._buffers = list()
        self._is_dirty = list()

        self._depth = depth
        self._cam_count = cam_count
        self._frames_per_camera = frames_per_camera
        self._primary = primary

        self._buffer_index = Value(ctypes.c_uint32, 0)

        self._batch_index = list()
        for cdx in range(cam_count):
            self._batch_index.append(Value(ctypes.c_uint32, 0))

        self._read_index = Value(ctypes.c_uint32, 0)

        self._shape = shape
        self._byte_count = shape[0] * shape[1]

        for idx in range(self._depth):
            buffer = list()
            for cdx in range(self._cam_count):
                cam_buffer = list()
                for bdx in range(self._frames_per_camera):
                    cam_buffer.append(RawArray(ctypes.c_ubyte, self._byte_count))
                buffer.append(cam_buffer)

            self._buffers.append(buffer)
            self._is_dirty.append(Value(ctypes.c_bool, False))

        self._frame_indexing = numpy.repeat([i for i in range(self._frames_per_camera)], self._cam_count)
        self._camera_indexing = numpy.tile([i for i in range(self._cam_count)], self._frames_per_camera)

        self._frame_dest = numpy.zeros(self._shape, dtype='uint8')

        self._overflow_count = 0

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
        return self._buffer_index.value

    def reset(self):
        self._buffer_index.value = 0

        for idx in range(self._cam_count):
            self._is_dirty[idx].value = False

        for cdx in range(self._cam_count):
            self._batch_index[cdx].value = 0

        self._read_index.value = 0

        self._overflow_count = 0

    def put(self, content, camera, allow_overflow: bool = True) -> BufferResult:
        buffer_index = self._buffer_index.value

        is_overflow = self._is_dirty[buffer_index].value

        if is_overflow:
            self._overflow_count += 1
            if not allow_overflow:
                return BufferResult.Overflow

        try:
            memoryview(self._buffers[buffer_index][camera][self._batch_index[camera].value]).cast("B")[
            :] = content.flatten()
        except IndexError:
            logger.error(f"IndexError {buffer_index} {camera} {self._batch_index[camera].value}")

        self._batch_index[camera].value += 1

        if self._batch_index[camera].value == self._frames_per_camera:
            self._batch_index[camera].value = 0
            if camera == self._primary:
                self._is_dirty[buffer_index].value = True

                buffer_index += 1
                if buffer_index == self._depth:
                    buffer_index = 0

                self._buffer_index.value = buffer_index

        return BufferResult.Ok if not is_overflow else BufferResult.Overflow

    def get_output(self, output: numpy.ndarray):
        if not self._is_dirty[self._read_index.value].value:
            return False

        buffer = self._buffers[self._read_index.value]

        for idx, cdx in enumerate(self._camera_indexing):
            self._frame_dest[:, :] = numpy.frombuffer(buffer[cdx][self._frame_indexing[idx]], "uint8",
                                                      self._byte_count).reshape(self.shape)
            for fn in range(3):
                output[idx, :, :, fn] = self._frame_dest

        self._is_dirty[self._read_index.value].value = False

        self._read_index.value += 1

        if self._read_index.value == self._depth:
            self._read_index.value = 0

        return True

    def empty(self) -> bool:
        return not self._is_dirty[self._read_index.value].value
