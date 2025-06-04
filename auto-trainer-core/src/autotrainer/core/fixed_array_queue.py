import ctypes
import logging
import multiprocessing
import queue
import time
from enum import IntEnum
from multiprocessing import RawArray, Value
from multiprocessing.context import BaseContext
from typing import List, Optional

import numpy

from autotrainer.core.multiproc import get_mp_ctx

logger = logging.getLogger(__name__)


class BufferResult(IntEnum):
    Ok = 0
    Overflow = 1


class FixedArrayQueue:
    def __init__(self, depth: int, shape: (int, int), name: str="noname", *,
                 mp_ctx: Optional[BaseContext] = None,
    ):
        if mp_ctx is None:
            mp_ctx = get_mp_ctx()

        self._name = name
        # indexing: [buffer]
        self._buffers: List[RawArray] = []
        self._is_dirty: List[Value] = []

        self._depth = depth
        self._shape = shape
        self._byte_count = shape[0] * shape[1]

        self._buffer_index = 0
        self._read_index = 0

        self._buff_views = []
        for idx in range(self._depth):
            self._buffers.append(mp_ctx.RawArray(ctypes.c_ubyte, self._byte_count))
            self._is_dirty.append(mp_ctx.Value(ctypes.c_bool, False))

        self._next_counts_log_time = time.time()
        self._overflow_count = 0
        self._put_count = 0

    def __str__(self):
        return f"{self.__class__.__name__}({self._name!r})"

    @property
    def shape(self):
        return self._shape

    @property
    def buffer_index(self) -> int:
        return self._buffer_index

    # unused
    def reset(self):
        self._buffer_index = self._read_index = 0

    def put(self, content: numpy.ndarray):
        return self._put(content)

    def _put(self, content: numpy.ndarray):
        self._buff_views.clear()
        for idx in range(self._depth):
            self._buff_views.append(memoryview(self._buffers[idx]).cast("B"))
        self.put = self._put = self._put_view
        return self._put_view(content)

    def _put_view(self, content: numpy.ndarray) -> BufferResult:
        buffer_index = self._buffer_index
        is_overflow = self._is_dirty[buffer_index].value
        if is_overflow:
            self._overflow_count += 1
            return BufferResult.Overflow

        self._put_count += 1

        # t = time.time()
        # if t > self._next_counts_log_time:
        #     self._next_counts_log_time += 10
        #     logger.info("%s: put=%s overflow=%s", self, self._put_count, self._overflow_count)
        #     self._put_count = self._overflow_count = 0

        self._buff_views[buffer_index][:] = content.reshape(-1)  # content.flatten()

        self._is_dirty[buffer_index].value = True

        buffer_index += 1
        buffer_index %= self._depth
        self._buffer_index = buffer_index

        return BufferResult.Ok if not is_overflow else BufferResult.Overflow

    def get(self, block: bool = False, timeout: float = 0) -> numpy.ndarray:
        step = 100
        rest = 1 / step
        for _ in range(0, 1 + int(timeout * 1000), step):
            read_index = self._read_index
            if self._is_dirty[read_index].value:
                break
            time.sleep(rest)
        else:
            raise queue.Empty

        buffer = self._buffers[read_index]

        v = numpy.frombuffer(buffer, "uint8", self._byte_count).reshape(self.shape)
        output = v.copy()  # numpy.frombuffer() returns a view

        self._is_dirty[read_index].value = False

        self._read_index = (read_index + 1) % self._depth

        return output

    # noinspection PyMethodMayBeStatic
    def empty(self) -> bool:
        return True

    # noinspection PyMethodMayBeStatic
    def qsize(self) -> int:
        return 0
