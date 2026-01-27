import multiprocessing
import threading


def get_mp_ctx():
    return multiprocessing.get_context("spawn")



class DaemonTimer(threading.Timer):
    """A Timer that does not block main process exit"""

    def __init__(self, delay, func, args=None, kwargs=None):
        super().__init__(delay, func, args=args, kwargs=kwargs)
        self.daemon = True


def make_daemon_timer(delay, func, *args, **kwargs):
    return DaemonTimer(delay, func, *args, **kwargs)


no_op_timer = make_daemon_timer(0, lambda: None)
no_op_timer.finished.set()
