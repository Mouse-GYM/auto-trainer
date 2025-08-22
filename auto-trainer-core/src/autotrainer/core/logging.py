import copy
import dataclasses
import functools
import logging.handlers
import multiprocessing
import os
import signal
import threading
import time
from queue import Empty
from multiprocessing import Process
from typing import Optional, Dict, Union, TextIO, List

import sys
import verboselogs
import coloredlogs
from datetime import datetime

_LogLevelT = Union[str, int]


_already_setup = False
_multiprocess_log_queue: Optional[multiprocessing.Queue] = None
_queue_listener: Optional[logging.handlers.QueueListener] = None
_queue_handler: Optional[logging.Handler] = None
_console_handler: Optional[logging.StreamHandler] = None
_root_handler = None


DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
MULTIPROC_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s[%(processName)s.%(process)d-%(threadName)s.%(thread_id)s] %(message)s"


# these loggers can be too verbose:
_limit_loggers_level = {
    'botocore': {
        'level': 'INFO'
    },
    'boto3': {
        'level': 'INFO'
    },
    'urllib3': {
        'level': 'INFO'
    },
    'py4j': {
        'level': 'INFO'
    },
    'h5py': {
        'level': 'INFO'
    }
}


class DateTimeFormats:
    # could be an enum eventually
    hour_time_precise = "%H:%M:%S.%f"
    month_day_time_precise = f"%m/%d {hour_time_precise}"
    year_precise = f"%Y/%m/%d {hour_time_precise}"


DEFAULT_FIELD_STYLES = dict(
    asctime=dict(color='white', bold=False),
    hostname=dict(color='magenta'),
    levelname=dict(color='blue', bold=True),
    name=dict(color='cyan', bold=False),
    programname=dict(color='cyan'),
    username=dict(color='yellow'),
)


DEFAULT_LEVEL_STYLES = dict(
    spam=dict(color='white', faint=True),
    debug=dict(color='white', bold=False, faint=False),
    verbose=dict(color='white', bold=True),
    info=dict(color='blue', bold=False, faint=True),
    notice=dict(color='magenta', faint=True),
    warning=dict(color='yellow'),
    success=dict(color='green', bold=False),
    error=dict(color='red', bold=False, faint=True),
    critical=dict(color='red', bold=True),
)


@dataclasses.dataclass
class LogConfig:
    base_logger_name: Optional[str] = None  # i.e: "root" logger if None
    logger_level: _LogLevelT = logging.NOTSET
    root_level: _LogLevelT = logging.NOTSET
    log_format: str = MULTIPROC_LOG_FORMAT
    date_format: str = DateTimeFormats.hour_time_precise
    time_precision: int = 3,  # for sub seconds precision, nbr of digits after the dot.
    level_styles: Dict[str, Dict[str, str]] = dataclasses.field(default_factory=copy.deepcopy(DEFAULT_LEVEL_STYLES))
    field_styles: Dict[str, Dict[str, str]] = dataclasses.field(default_factory=copy.deepcopy(DEFAULT_FIELD_STYLES))
    stream: str = "sys.stdout"


def listener_command(func):
    @functools.wraps(func)
    def wrapped(self, *args, **kwargs):
        self._send_command(func.__name__, (args, kwargs))
    return wrapped


class LogQueueListenerProc(Process):

    def __init__(
        self,
        log_queue,
        log_config: LogConfig,
    ):
        super().__init__(daemon=True)
        self._queue = log_queue
        self._command_queue = multiprocessing.Queue()
        self._config = log_config
        self._console_handler = None
        self._listener = None

    def _send_command(self, cmd, data):
        self._command_queue.put((cmd, data))

    @listener_command
    def set_handler_level(self, name, level):
        """Set handler level"""

    def _set_handler_level(self, name, level):
        self._console_handler.setLevel(level)

    @listener_command
    def add_file_handler(self, path):
        """Add file handler to path"""

    def _add_file_handler(self, path):
        logger.info("Adding file handler ...")
        file_handler = logging.FileHandler(path)
        file_handler.addFilter(thread_id_filter)
        file_handler.setFormatter(
            PreciseTimeFormatter(
                MULTIPROC_LOG_FORMAT,
                datefmt=DateTimeFormats.year_precise,
                time_precision=6,
            )
        )
        file_handler.setLevel(verboselogs.SPAM + 1)  # writes everything up to DEBUG which reaches it
        self._listener.handlers += (file_handler,)
        logger.info("logging.root.handlers=%s ; listener_handlers=%s",
                    logging.root.handlers, self._listener.handlers)

    def stop(self):
        self._command_queue.put(None)
        # os.kill(self.pid, signal.SIGINT)
        self.join()

    def run(self):
        # print(f"{logging.root.handlers}")
        cfg = self._config
        stream = sys.stdout  # for now
        self._console_handler = console_handler = logging.StreamHandler(stream=stream)
        console_handler.addFilter(thread_id_filter)
        fmt = ColoredPreciseTimeFormatter(
            cfg.log_format,
            level_styles=cfg.level_styles,
            field_styles=cfg.field_styles,
            datefmt=cfg.date_format,
            time_precision=cfg.time_precision,
        )
        console_handler.setFormatter(fmt)

        root_handler = console_handler

        base_logger = get_verbose_logger(cfg.base_logger_name)
        base_logger.addHandler(root_handler)
        base_logger.setLevel(cfg.root_level)

        listener = self._listener = WithThreadIdQueueListener(
            self._queue,
            console_handler,
            respect_handler_level=True,
        )
        listener.start()

        command_q = self._command_queue
        while True:
            try:
                data = command_q.get(1)
            except Empty:
                continue
            if data is None:
                break
            cmd = data[0]
            args, kwargs = data[1]
            meth = getattr(self, f"_{cmd}", None)
            if meth is None:
                logger.warning("unknown command: %sr", cmd)
                continue
            meth(*args, **kwargs)
        # end while True
        listener.stop()


def get_root_handler():
    return _root_handler


def get_console_handler() -> logging.Handler:
    return _console_handler


def get_multiprocess_log_queue() -> Optional[multiprocessing.Queue]:
    return _multiprocess_log_queue


def get_queue_listener() -> Optional[LogQueueListenerProc]:
    return _queue_listener


def get_queue_handler():
    return _queue_handler


class ThreadIdFilter(logging.Filter):

    def filter(self, record):
        """Inject thread_id to log records"""
        if not hasattr(record, "thread_id"):
            record.thread_id = threading.get_native_id()
        return True


thread_id_filter = ThreadIdFilter()


class PreciseTimeFormatter(logging.Formatter):
    """A logger formatter with time precision handling"""

    converter = datetime.fromtimestamp

    def __init__(self, *args, time_precision: int = 3, **kwargs):
        self._time_precision = time_precision
        super().__init__(*args, **kwargs)

    def formatTime(self, record, datefmt=None):
        ct = self.converter(record.created)
        if not datefmt:
            datefmt = DateTimeFormats.year_precise  # "%Y-%m-%d %H:%M:%S.%f"
        if self._time_precision > 0 and "%f" in datefmt:
            msec_len = len(str(int(record.msecs)))
            v = str(record.msecs).replace(".", "")
            v0 = "0" * (3 - msec_len)
            v = (v0 + v)[:self._time_precision]
        else:
            v = ""
        with_dot = ".%f" in datefmt
        rep = f".%f" if with_dot and self._time_precision == 0 else "%f"
        datefmt = datefmt.replace(rep, v)
        s = ct.strftime(datefmt)
        return s


class ColoredPreciseTimeFormatter(PreciseTimeFormatter, coloredlogs.ColoredFormatter):
    """A colored logger formatter with time precision handling"""


def stop_multiproc_logging():
    global _multiprocess_log_queue, _queue_listener, _queue_handler, _console_handler
    if _queue_listener is not None:
        # must be before following log queue close()
        _queue_listener.stop()
        _queue_listener = None

    if _multiprocess_log_queue is not None:
        _multiprocess_log_queue.close()
        _multiprocess_log_queue.join_thread()
        _multiprocess_log_queue = None

    if _queue_handler is not None:
        _queue_handler.close()
        _queue_handler = None


class WithThreadIdQueueListener(logging.handlers.QueueListener):
    def prepare(self, record):
        thread_id_filter.filter(record)
        return record


class WithThreadIdQueueHandler(logging.handlers.QueueHandler):

    def prepare(self, record):
        record = super().prepare(record)
        thread_id_filter.filter(record)
        return record


class VerboseLoggerWithThreadId(verboselogs.VerboseLogger):
    def filter(self, record):
        return thread_id_filter.filter(record)


def setup_logging(
    name: str = "autotrainer",
    *,
    base_logger_name: Optional[str] = None,  # i.e: "root" logger if None
    logger_level: _LogLevelT = logging.NOTSET,
    root_level: _LogLevelT = logging.NOTSET,
    log_format: str = MULTIPROC_LOG_FORMAT,
    date_format: str = DateTimeFormats.hour_time_precise,
    time_precision: int = 3,  # for sub seconds precision, nbr of digits after the dot.
    level_styles: Optional[Dict[str, Dict[str, str]]] = None,
    field_styles: Optional[Dict[str, Dict[str, str]]] = None,
    stream: TextIO = sys.stdout,
    multiprocess_enabled: bool = False,
    fork_method: str = "spawn",
    use_log_queue_handler: bool = False,
) -> verboselogs.VerboseLogger:
    global _already_setup
    global _multiprocess_log_queue, _queue_listener, _queue_handler, _console_handler, _root_handler

    if _already_setup:
        return get_verbose_logger(name)

    # actually we do not require this:
    # verboselogs.install()  # thx to get_verbose_logger function above.

    if level_styles is None:
        level_styles = DEFAULT_LEVEL_STYLES
    if field_styles is None:
        field_styles = DEFAULT_FIELD_STYLES
    #
    cfg = LogConfig(
        base_logger_name=base_logger_name,
    logger_level=logger_level,
    root_level=root_level,
    log_format=log_format,
    date_format=date_format,
    time_precision=time_precision,
    level_styles=level_styles,
    field_styles=field_styles,
    # stream: TextIO = sys.stdout,
    )
    #
    stop_multiproc_logging()
    #
    base_logger = get_verbose_logger(base_logger_name)
    #
    if multiprocess_enabled:
        # using queue created using the desired fork method context:
        multiproc_ctx = multiprocessing.get_context(fork_method)
        _multiprocess_log_queue = log_queue = multiproc_ctx.Queue()

        listener = LogQueueListenerProc(log_queue, cfg)
        listener.start()
        _queue_listener = listener  # keep global ref to ensure it stays alive
        queue_handler = WithThreadIdQueueHandler(log_queue)
        # queue_handler.setLevel(1)
        _queue_handler = queue_handler  # keep global ref to ensure it stays alive
        # root_handler = console_handler if not use_log_queue_handler else queue_handler
        root_handler = _root_handler = queue_handler
        console_handler = _console_handler = logging.Handler()
        console_handler.setLevel = lambda l: listener.set_handler_level("console_handler", l)
    else:
        console_handler = _console_handler = logging.StreamHandler(stream=stream)
        root_handler = _root_handler = console_handler
    #
        console_handler.addFilter(thread_id_filter)
        fmt = ColoredPreciseTimeFormatter(
            log_format,
            level_styles=level_styles,
            field_styles=field_styles,
            datefmt=date_format,
            time_precision=time_precision,
        )
        console_handler.setFormatter(fmt)
        # console_handler.setLevel(logger_level)

        root_handler = console_handler
        base_logger.addHandler(root_handler)
        base_logger.setLevel(root_level)

    #

    logger.info("Setup logging ; %s", base_logger.handlers)

    get_verbose_logger("transitions").setLevel(logger_level)
    get_verbose_logger("tools").setLevel(logger_level)
    get_verbose_logger("autotrainer").setLevel(logger_level)
    get_verbose_logger("inference_algorithms").setLevel(logger_level)

    for _limit_name, v in _limit_loggers_level.items():
        logging.getLogger(_limit_name).setLevel(v["level"])

    desired_logger = get_verbose_logger(name)
    desired_logger.setLevel(logger_level)

    _already_setup = True

    return desired_logger


def set_logger_level(context: Dict[str, Union[str, int]]):
    for name, value in context.items():
        logging.getLogger(name).setLevel(value)


def make_log_dict_config(*, root_log_level, log_queue):
    # usable by logging.config.dictConfig
    dct_cfg = {
        'version': 1,
        'disable_existing_loggers': False,
        'handlers': {
            'queue': {
                'class': 'autotrainer.core.logging.WithThreadIdQueueHandler',
                'queue': log_queue,
                'level': logging.NOTSET,  # pass everything to the listener
            }
        },
        # root logger is here:
        'root': {
            'handlers': ['queue'],
            # with its own level here:
            'level': logging.NOTSET,  # root_log_level,
        },
        # but eventual level of other loggers have to be defined here:
        'loggers': copy.deepcopy(_limit_loggers_level),
    }
    return dct_cfg


def get_verbose_logger(name: Optional[str] = None) -> VerboseLoggerWithThreadId:
    obj = logging.getLogger(name)
    if not isinstance(obj, VerboseLoggerWithThreadId):
        obj.__class__ = VerboseLoggerWithThreadId
    assert isinstance(obj, VerboseLoggerWithThreadId)
    return obj


logger = get_verbose_logger(__name__)
