import logging
from typing import Optional

import verboselogs


def get_verbose_logger(name: Optional[str] = None) -> verboselogs.VerboseLogger:
    logger = logging.getLogger(name)
    if isinstance(logger, verboselogs.VerboseLogger):
        return logger
    logger.__class__ = verboselogs.VerboseLogger
    assert isinstance(logger, verboselogs.VerboseLogger)
    return logger
