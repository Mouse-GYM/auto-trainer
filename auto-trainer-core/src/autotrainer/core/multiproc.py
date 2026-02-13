import logging.config
import multiprocessing
import signal
import threading

from autotrainer.core.logging import setup_logging, install_log_exception_hook, get_verbose_logger


logger = get_verbose_logger(__name__)


def get_mp_ctx():
    return multiprocessing.get_context("spawn")



class DaemonTimer(threading.Timer):
    """A Timer that does not block main process exit"""

    finished: threading.Event

    def __init__(self, delay, func, args=None, kwargs=None):
        super().__init__(delay, func, args=args, kwargs=kwargs)
        self.daemon = True


def make_daemon_timer(delay, func, *args, **kwargs):
    return DaemonTimer(delay, func, *args, **kwargs)


def pool_init(log_dict_cfg=None):
    """For process pool"""
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    if log_dict_cfg is None:
        setup_logging()
    else:
        logging.config.dictConfig(log_dict_cfg)
        install_log_exception_hook()
    logger.info("Initialized pool worker")


no_op_timer = make_daemon_timer(0, lambda: None)
no_op_timer.finished.set()
