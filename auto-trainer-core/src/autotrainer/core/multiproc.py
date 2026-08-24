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

#

if False:
    def log(s):
        """disabled"""
else:
    log = print


def _wait_children(children, timeout):
    p_end = get_perf_now() + timeout
    while True:
        if get_perf_now() > p_end:
            log("timeout waiting children processes exited")
            break
        for proc in list(children):
            if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
                children.remove(proc)
        if not children:
            log("No more children processes, exiting")
            break
        time.sleep(0.1)


def _filt_children(children, filt_pid):
    return [proc for proc in children if proc.pid != filt_pid]


def _monitor_pid(monitored_pid):
    this_pid = os.getpid()
    try:
        monitored_proc = psutil.Process(pid=monitored_pid)
        prev_children = _filt_children(monitored_proc.children(recursive=True), this_pid)
    except psutil.NoSuchProcess:
        # unusual/abnormal case, nothing we can do.
        return
    log(f"Started monitor pid {monitored_pid} ; parent pid = {os.getppid()} ; pid={this_pid} ; childs={prev_children}")
    while True:
        try:
            children = _filt_children(monitored_proc.children(recursive=True), this_pid)  # get children list before check status
        except psutil.NoSuchProcess:
            break
        if children != prev_children:
            log(f"detected child pids change: prev={children} new={prev_children}")
        if not monitored_proc.is_running() or monitored_proc.status() == psutil.STATUS_ZOMBIE:
            break
        prev_children = children  # and only assign after check status
        # monitored_proc.wait(1)  not a big deal if delayed by up to 1s for the below steps
        time.sleep(1)
    # ensure/give other child processes which are monitoring the _main_watchdog_timeout their timeout is reached:
    log(f"monitored proc: {monitored_proc} - children: {prev_children}")
    # NB: give relatively more delay for waiting on children processes to exit,
    # to better ensure they can exit gracefully.
    _wait_children(prev_children, _main_watchdog_timeout + 5)
    for proc in prev_children:
        if proc.is_running():
            log(f"Signaling (TERM) proc {proc}")
            try:
                proc.send_signal(signal.SIGTERM)
            except Exception:
                pass
    time.sleep(0.1)
    _wait_children(prev_children, 1)
    for proc in prev_children:
        if proc.is_running():
            log(f"Signaling (KILL) proc={proc}")
            try:
                proc.kill()
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
