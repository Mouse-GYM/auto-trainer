import os
import logging.config
import multiprocessing
import signal
import threading
from multiprocessing.sharedctypes import Synchronized
from typing import Optional

from autotrainer.core import get_perf_now


def get_mp_ctx():
    """Using on purpose the spawn mp context"""
    return multiprocessing.get_context("spawn")


class EmptyWithContext:

    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


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
    # this is to prevent keyboard interrupted being delivered to all child processes of the main process:
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    # given by default this is what is done.
    # inner-import on purpose: prevent import loop:
    from autotrainer.core.logging import setup_logging, install_log_exception_hook
    if log_dict_cfg is None:
        setup_logging()
    else:
        logging.config.dictConfig(log_dict_cfg)
        install_log_exception_hook()
    logging.root.info("Initialized pool worker")


_default_main_watchdog_timeout = 15
try:
    _main_watchdog_timeout = float(os.getenv("AUTOTRAINER_MAIN_WATCHDOG_TIMEOUT", _default_main_watchdog_timeout))
except ValueError:
    _main_watchdog_timeout = _default_main_watchdog_timeout


class MixinMainWatchdogChecker:

    main_watchdog_holder: Optional[Synchronized] = None
    main_watchdog_timeout: float = _main_watchdog_timeout

    def check_main_watchdog(self) -> bool:
        """Return True if "alive" (or not configured), False if timedout"""
        holder = self.main_watchdog_holder
        if holder is None:
            return True
        p_now = get_perf_now()
        return p_now - holder.value < self.main_watchdog_timeout


no_op_timer = make_daemon_timer(0, lambda: None)
no_op_timer.finished.set()
