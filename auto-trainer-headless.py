import logging
import os
import time
import sys
import argparse
import faulthandler
from multiprocessing import set_start_method


def update_log_level(value: int):
    logging.getLogger("inference_algorithms").setLevel(value)
    logging.getLogger("tools").setLevel(value)
    logging.getLogger("autotrainer").setLevel(value)

    if value == logging.DEBUG:
        logging.getLogger("transitions").setLevel(logging.INFO)
    else:
        logging.getLogger("transitions").setLevel(logging.WARNING)


def main():
    from tools.acquisition.model.user_preferences import UserPreferences
    from tools.acquisition.model.app_model import AppModel

    from autotrainer.core.logging import get_verbose_logger
    logger = get_verbose_logger()

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

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        app_view_model.on_capture_stop()
        return 0


if __name__ == '__main__':
    faulthandler.enable()
    set_start_method("spawn")

    from autotrainer.core.logging import setup_logging
    setup_logging()

    sys.exit(main())
