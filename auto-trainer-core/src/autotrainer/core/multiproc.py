import multiprocessing
import threading


def get_mp_ctx():
    return multiprocessing.get_context("spawn")



class DaemonTimer(threading.Timer):
    """A Timer that does not block main process exit"""

    def __init__(self, delay, func, args=None, kwargs=None):
        super().__init__(delay, func, args=args, kwargs=kwargs)
        self.daemon = True
