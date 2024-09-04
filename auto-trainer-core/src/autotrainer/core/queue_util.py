from multiprocessing import Queue


def clear_queue(queue: Queue):
    """Empty a queue."""
    if queue is None:
        return

    while queue.empty() is False or queue.qsize() > 0:
        try:
            queue.get_nowait()
        except:
            pass


def trim_queue(queue: Queue, limit: int) -> bool:
    """Trim queue length to the specified limit."""
    if queue is None:
        return False

    trimmed = False

    while queue.qsize() > limit:
        try:
            queue.get_nowait()
            trimmed = True
        except:
            pass

    return trimmed
