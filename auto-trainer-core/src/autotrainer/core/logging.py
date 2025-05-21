import logging
from typing import Optional, Dict, Union

import sys
import verboselogs
import coloredlogs


DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s | %(message)s"
MULTIPROC_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s[%(processName)s.%(process)d-%(threadName)s] | %(message)s"

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

_already_setup = False


def setup_logging(
    name: str = "main",
    *,
    base_logger_name: Optional[str] = None,  # i.e: "root" logger if None
    logger_level: str = logging.NOTSET,
    root_level: str = logging.INFO,
    log_format: str = MULTIPROC_LOG_FORMAT,
    date_format: str = "%H:%M:%S.%f",
    level_styles: Optional[Dict[str, Dict[str, str]]] = None,
    field_styles: Optional[Dict[str, Dict[str, str]]] = None,
    stream = sys.stdout,
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
    if False:
        fmt = logging.Formatter(
        log_format,
        datefmt=date_format,
    )
    else:
        fmt = coloredlogs.ColoredFormatter(
        log_format,
        level_styles=level_styles,
        field_styles=field_styles,
        datefmt=date_format,
    )
    console_handler.setFormatter(fmt)
    console_handler.setLevel(logger_level)

    root_handler = console_handler

    base_logger = get_verbose_logger(base_logger_name)
    base_logger.addHandler(root_handler)
    base_logger.setLevel(root_level)

    logger = get_verbose_logger(name)
    _already_setup = True

    return logger


def set_logger_level(context: Dict[str, Union[str, int]]):
    for name, value in context.items():
        logging.getLogger(name).setLevel(value)
