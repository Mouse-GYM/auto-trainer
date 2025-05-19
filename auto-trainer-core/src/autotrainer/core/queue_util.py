import sys
from queue import Empty
from multiprocessing import Queue
from typing import Union

from autotrainer.core import FixedArrayQueue
from autotrainer.core.logging import get_verbose_logger

logger = get_verbose_logger(__name__)


def clear_queue(queue: Union[Queue, FixedArrayQueue]):
    """Empty a queue."""
    if queue is None or sys.platform == "darwin":
        return

    warned = False
    while not queue.empty() or queue.qsize() > 0:
        try:
            queue.get_nowait()
        except Empty:
            empty = queue.empty()
            qsize = queue.qsize()
            if not empty or qsize > 0:
                if not warned:
                    warned = True
                    logger.warning("queue %s: raised Empty but empty()=%s and qsize()=%s",
                                   queue, empty, qsize)
                continue
            break


def trim_queue(queue: Queue, limit: int) -> bool:
    """Trim queue length to the specified limit."""
    if queue is None or sys.platform == "darwin":
        return False

    trimmed = False

    while queue.qsize() > limit:
        try:
            queue.get_nowait()
            trimmed = True
        except Empty:
            pass

    return trimmed
