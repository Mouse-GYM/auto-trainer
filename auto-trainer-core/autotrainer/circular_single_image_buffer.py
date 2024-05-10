import ctypes
import logging
import queue
import time
from enum import IntEnum
from multiprocessing import RawArray, Value

import numpy

logger = logging.getLogger(__name__)


class BufferResult(IntEnum):
    Ok = 0,
    Overflow = 1,


class CircularSingleImageBuffer:
    def __init__(self, depth: int, shape: (int, int)):
        # indexing: [buffer]
        self._buffers = list()
        self._is_dirty = list()

        self._depth = depth

        self._buffer_index = Value(ctypes.c_uint32, 0)

        self._read_index = Value(ctypes.c_uint32, 0)

        self._shape = shape
        self._byte_count = shape[0] * shape[1]

        for idx in range(self._depth):
            self._buffers.append(RawArray(ctypes.c_ubyte, self._byte_count))
            self._is_dirty.append(Value(ctypes.c_bool, False))

        self._frame_dest = numpy.zeros(self._shape, dtype='uint8')

    @property
    def shape(self):
        return self._shape

    @property
    def buffer_index(self) -> int:
        return self._buffer_index.value

    def reset(self):
        self._buffer_index.value = 0
        self._read_index.value = 0

    def put(self, content) -> BufferResult:
        buffer_index = self._buffer_index.value

        is_overflow = self._is_dirty[buffer_index].value

        try:
            memoryview(self._buffers[buffer_index]).cast("B")[:] = content.flatten()
        except IndexError:
            logger.error(f"IndexError {buffer_index}")

        self._is_dirty[buffer_index].value = True

        buffer_index += 1

        if buffer_index == self._depth:
            buffer_index = 0

        self._buffer_index.value = buffer_index

        return BufferResult.Ok if not is_overflow else BufferResult.Overflow

    def get(self, block: bool = False, timeout: float = 0):
        read_index = self._read_index.value

        if not self._is_dirty[read_index].value:
            time.sleep(timeout)
            raise queue.Empty

        buffer = self._buffers[read_index]

        output = self._frame_dest[:, :] = numpy.frombuffer(buffer, "uint8", self._byte_count).reshape(self.shape)

        self._is_dirty[read_index].value = False

        read_index += 1

        if read_index == self._depth:
            read_index = 0

        self._read_index.value = read_index

        return output

    def empty(self) -> bool:
        return True

    def qsize(self) -> int:
        return 0
