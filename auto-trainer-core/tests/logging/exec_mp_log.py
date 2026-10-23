import time
import logging
import sys

from autotrainer.core.logging import setup_logging, get_log_queue_listener, stop_multiproc_logging


def exec_mp_file_handler(log_path):
    setup_logging(multiprocess_enabled=True)
    logger = logging.getLogger(__name__)
    logger.info("START")
    time.sleep(1)
    listener = get_log_queue_listener()
    assert listener is not None
    logger.info("BEFORE")
    listener.add_file_handler(log_path)
    logger.info("AFTER")
    for idx in range(100):
        logger.info("CLOSE#%s", idx)
    stop_multiproc_logging()


if __name__ == "__main__":
    exec_mp_file_handler(sys.argv[-1])  # nb: argv[0] is __name__
