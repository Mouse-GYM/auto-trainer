from multiprocessing import Queue


def clear_queue(queue: Queue):
    if queue is None:
        return

    while queue.empty() is False or queue.qsize() > 0:
        try:
            queue.get_nowait()
        except:
            pass
