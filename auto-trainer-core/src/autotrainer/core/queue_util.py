import sys
import queue
from queue import Empty
import multiprocessing
from typing import Union, Optional

from autotrainer.core.logging import get_verbose_logger

logger = get_verbose_logger(__name__)


def clear_queue(queue_or_none: Optional[Union[queue.Queue, multiprocessing.Queue]],
                *, log_dumped: bool=False, name: str=""):
    """Empty a queue."""
    if queue_or_none is None:
        return
    is_darwin = sys.platform == "darwin"
    if not name:
        name = str(queue_or_none)
    flushed = 0
    task_done = getattr(queue_or_none, "task_done", lambda: None)
    try:
        while True:
            if not is_darwin:
                if queue_or_none.empty() and queue_or_none.qsize() == 0:
                    break
            try:
                obj = queue_or_none.get_nowait()
                flushed += 1
                task_done()
                if log_dumped:
                    logger.debug("queue %s: flushed %s: %s", name, type(obj), obj)
            except Empty:
                if is_darwin:
                    break
                empty = queue_or_none.empty()
                qsize = queue_or_none.qsize()
                if not empty or qsize > 0:
                    logger.warning("queue %s: raised Empty but empty()=%s and qsize()=%s",
                                   name, empty, qsize)
                    # continue
                break
    except Exception as err:
        logger.error("Could not clear queue %s: %s", name, err)

    logger.debug("queue %s: flushed %s items", name, flushed)
