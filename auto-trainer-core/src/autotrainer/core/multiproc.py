import math
import os
import sys
import logging.config
import multiprocessing
import signal
import threading
import time
from multiprocessing.managers import SyncManager, ValueProxy
from multiprocessing.sharedctypes import Synchronized
from typing import Optional

import psutil

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

    main_watchdog_holder: Optional[ValueProxy] = None
    main_watchdog_timeout: float = _main_watchdog_timeout

    def check_main_watchdog(self) -> bool:
        """Return True if "alive" (or not configured), False if timedout"""
        holder = self.main_watchdog_holder
        if holder is None:
            return True
        try:
            main_watch_perf_c = holder.value
        except (ValueError, OSError, EOFError, IOError):
            return False  # consider as dead as well
        if math.isnan(main_watch_perf_c):
            return True
        p_now = get_perf_now()
        return p_now - main_watch_perf_c < self.main_watchdog_timeout


no_op_timer = make_daemon_timer(0, lambda: None)
no_op_timer.finished.set()


def _get_child_pids(pid):
    current_process = psutil.Process(pid=pid)
    children = current_process.children(recursive=True)
    return sorted(child.pid for child in children)


def _monitor_pid(monitored_pid):
    this_pid = os.getpid()
    prev_child_pids = _get_child_pids(monitored_pid)
    if False:
        def log(s):
            """disabled"""
    else:
        log = print
    log(f"Started monitor pid {monitored_pid} ; parent pid = {os.getppid()} ; pid={this_pid} ; childs={prev_child_pids}")
    while True:
        try:
            child_pids = _get_child_pids(monitored_pid)
        except psutil.NoSuchProcess:
            break
        if child_pids != prev_child_pids:
            log(f"detected child pids change: prev={prev_child_pids} new={child_pids}")
        prev_child_pids = child_pids
        time.sleep(1)
    log(f"Monitored process pid={monitored_pid} died")
    # ensure/give other child processes which are monitoring the _main_watchdog_timeout their timeout is reached:
    time.sleep(_main_watchdog_timeout + 3)
    for c_pid in prev_child_pids or []:
        if c_pid != os.getpid():
            log(f"killing pid={c_pid}")
            try:
                os.kill(c_pid, signal.SIGTERM)
            except Exception:
                pass
    time.sleep(0.5)
    for c_pid in prev_child_pids or []:
        if c_pid != this_pid:
            log(f"killing pid={c_pid}")
            try:
                os.kill(c_pid, signal.SIGKILL)
            except Exception:
                pass
    log("exiting monitor pid")
    os.kill(this_pid, signal.SIGTERM)
    time.sleep(1)
    os.kill(this_pid, signal.SIGKILL)  # harakiri


def _init_monitor_pid(pid):
    thread = threading.Thread(target=_monitor_pid, daemon=True, args=(pid,))
    thread.start()


def make_multiproc_manager():
    m = SyncManager(ctx=get_mp_ctx())
    m.start(initializer=_init_monitor_pid, initargs=(os.getpid(),))
    return m
