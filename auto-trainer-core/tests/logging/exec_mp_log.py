import time
import logging
import sys

from autotrainer.core.logging import setup_logging, get_log_queue_listener


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
    time.sleep(0.5)  # necessary to give some time for add_file_handler to be processed,
    # given it's async command.


if __name__ == "__main__":
    exec_mp_file_handler(sys.argv[-1])  # nb: argv[0] is __name__
