import logging
import os
import time
import sys
import argparse
import faulthandler
from multiprocessing import set_start_method


def update_log_level(value: int):
    get_console_handler().setLevel(value)
    # logging.getLogger("inference_algorithms").setLevel(value)
    # logging.getLogger("tools").setLevel(value)
    # logging.getLogger("autotrainer").setLevel(value)
    #
    # if value == logging.DEBUG:
    #     logging.getLogger("transitions").setLevel(logging.INFO)
    # else:
    #     logging.getLogger("transitions").setLevel(logging.WARNING)


def main():
    from tools.acquisition.model.user_preferences import UserPreferences
    from tools.acquisition.model.app_model import AppModel

    from autotrainer.core.logging import get_verbose_logger

    logger = get_verbose_logger("main")

    parser = argparse.ArgumentParser()

    parser.add_argument("-c", "--configuration", help="configuration file", default=None, type=str)

    args = parser.parse_args()
    configuration = args.configuration

    if configuration and not os.path.exists(configuration):
        return -1

    preferences = UserPreferences()

    update_log_level(preferences.log_level)

    app_view_model = AppModel(preferences)

    app_view_model.load_configuration(configuration)

    app_view_model.on_activated()

    if not app_view_model.on_capture_start():
        logger.error("failed to start capture")
        return -1

    exit_rc = 1
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Interrupted, exiting..")
        exit_rc = 0
    except Exception as err:
        logger.exception("Fatal error: %s", err)

    app_view_model.on_capture_stop()

    return exit_rc


if __name__ == '__main__':
    faulthandler.enable()
    set_start_method("spawn")

    from autotrainer.core.logging import setup_logging, get_console_handler

    setup_logging(logger_level=logging.DEBUG, time_precision=6, multiprocess_enabled=True)

    sys.exit(main())
