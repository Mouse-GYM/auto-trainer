import logging
import threading
from typing import Optional, Dict, Union, TextIO

import sys
import verboselogs
import coloredlogs
from datetime import datetime

_already_setup = False

_LogLevelT = Union[str, int]

DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
MULTIPROC_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s[%(processName)s.%(process)d-%(threadName)s.%(thread_id)s] %(message)s"

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


def get_verbose_logger(name: Optional[str] = None) -> verboselogs.VerboseLogger:
    logger = logging.getLogger(name)
    if not isinstance(logger, verboselogs.VerboseLogger):
        logger.__class__ = verboselogs.VerboseLogger
    assert isinstance(logger, verboselogs.VerboseLogger)
    return logger


def _thread_id_filter(record):
    """Inject thread_id to log records"""
    record.thread_id = threading.get_native_id()
    return record


class _Formatter(coloredlogs.ColoredFormatter):

    converter = datetime.fromtimestamp

    def __init__(self, *args, time_precision: int = 3, **kwargs):
        self._time_precision = time_precision
        super().__init__(*args, **kwargs)

    def formatTime(self, record, datefmt=None):
        ct = self.converter(record.created)
        if not datefmt:
            datefmt = "%Y-%m-%d %H:%M:%S.%f"
        if self._time_precision > 0 and "%f" in datefmt:
            v = str(record.msecs * 1000).replace(".", "").ljust(self._time_precision, '0')[:self._time_precision]
        else:
            v = ""
        with_dot = ".%f" in datefmt
        rep = f".%f" if with_dot and self._time_precision == 0 else "%f"
        datefmt = datefmt.replace(rep, v)
        s = ct.strftime(datefmt)
        return s


def setup_logging(
    name: str = "main",
    *,
    base_logger_name: Optional[str] = None,  # i.e: "root" logger if None
    logger_level: _LogLevelT = logging.NOTSET,
    root_level: _LogLevelT = logging.INFO,
    log_format: str = MULTIPROC_LOG_FORMAT,
    date_format: str = "%H:%M:%S.%f",
    time_precision: int = 3,  # for sub seconds precision
    level_styles: Optional[Dict[str, Dict[str, str]]] = None,
    field_styles: Optional[Dict[str, Dict[str, str]]] = None,
    stream: TextIO = sys.stdout,
) -> verboselogs.VerboseLogger:
    global _already_setup

    if _already_setup:
        return get_verbose_logger(name)

    # actually we do not require this:
    # verboselogs.install()  # thx to get_verbose_logger function above.

    if level_styles is None:
        level_styles = DEFAULT_LEVEL_STYLES
    if field_styles is None:
        field_styles = DEFAULT_FIELD_STYLES
    #
    console_handler = logging.StreamHandler(stream=stream)
    console_handler.addFilter(_thread_id_filter)
    fmt = _Formatter(
        log_format,
        level_styles=level_styles,
        field_styles=field_styles,
        datefmt=date_format,
        time_precision=time_precision,
    )
    console_handler.setFormatter(fmt)
    console_handler.setLevel(logger_level)

    root_handler = console_handler

    base_logger = get_verbose_logger(base_logger_name)
    base_logger.addHandler(root_handler)
    base_logger.setLevel(root_level)

    #

    logging.getLogger("transitions").setLevel(logger_level)
    logging.getLogger("tools").setLevel(logger_level)
    logging.getLogger("autotrainer").setLevel(logger_level)
    logging.getLogger("inference_algorithms").setLevel(logger_level)

    logger = get_verbose_logger(name)
    logger.setLevel(logger_level)

    _already_setup = True

    return logger


def set_logger_level(context: Dict[str, Union[str, int]]):
    for name, value in context.items():
        logging.getLogger(name).setLevel(value)
